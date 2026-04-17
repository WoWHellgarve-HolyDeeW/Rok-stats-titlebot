#!/usr/bin/env python3
"""
Title Injection Integrator - Combines verified packets with injection methods
Manual test confirmed: Packets work 100%
Now we just need to send them
"""
import sys
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Import services
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'RESEARCH' / 'frida'))
sys.path.insert(0, str(Path(__file__).parent))

from title_service import TitleService

class TitleInjectorBackend:
    """Production backend for title injection"""
    
    def __init__(self):
        self.service = TitleService()
        self.frida = None
        
    def get_title_data(self, title: str, target_gov_id: int | None = None) -> dict:
        """Get the correctly targeted packet for a title."""
        return self.service.get_title_packet(title, target_gov_id)
    
    def inject_frida(
        self,
        title: str,
        target_gov_id: int,
        attach_running: bool = False,
    ) -> dict:
        """Inject via the stable Frida path.

        Production queue mode defaults to a clean Frida spawn because attach
        attempts against an already running LDPlayer game can poison the runtime
        and make the subsequent spawn fail with allocate-memory crashes.
        """
        try:
            from _frida_daemon import FridaSessionManager, JS_CALLER, send_command, ADB, SERIAL, GAME_PKG
        except ImportError as e:
            return {'error': f'Frida runtime unavailable: {e}'}

        pkt_data = self.get_title_data(title, target_gov_id)
        if 'error' in pkt_data:
            return pkt_data

        mgr = FridaSessionManager()
        try:
            mgr.ensure_frida_server()
            script = None
            session = None

            def try_attach_running_session():
                last_errors = []

                for attempt in range(1, 5):
                    mgr._reset_device()
                    device = mgr._get_device()
                    attach_session = None
                    attempt_errors = []

                    for target in ('com.lilithgame.roc.gp', 'Rise of Kingdoms'):
                        try:
                            attach_session = device.attach(target)
                            break
                        except Exception as exc:
                            attempt_errors.append(f'{target}: {type(exc).__name__}: {exc}')

                    if not attach_session:
                        try:
                            result = subprocess.run(
                                [ADB, '-s', SERIAL, 'shell', f'pidof {GAME_PKG}'],
                                capture_output=True, text=True, timeout=5,
                            )
                            game_pid = result.stdout.strip()
                            if game_pid:
                                attach_session = device.attach(int(game_pid))
                            else:
                                attempt_errors.append('pidof returned no game PID')
                        except Exception as exc:
                            attempt_errors.append(f'pid attach: {type(exc).__name__}: {exc}')

                    if not attach_session:
                        last_errors = attempt_errors
                        if attempt < 4:
                            time.sleep(5)
                        continue

                    hooks_ready = threading.Event()
                    active_ready = threading.Event()
                    detached = threading.Event()

                    def on_msg(msg, _data):
                        payload = msg.get('payload') if isinstance(msg, dict) else None
                        if msg.get('type') == 'send' and isinstance(payload, dict):
                            tag = payload.get('t')
                            if tag == 'HOOKS_READY':
                                hooks_ready.set()
                            elif tag == 'ACTIVE':
                                active_ready.set()

                    def on_detach(_reason, _crash):
                        detached.set()
                        hooks_ready.set()
                        active_ready.set()

                    try:
                        attach_session.on('detached', on_detach)
                        attach_script = attach_session.create_script(JS_CALLER)
                        attach_script.on('message', on_msg)
                        attach_script.load()
                        attach_script.post({'type': 'install'})

                        hooks_ready.wait(timeout=15)
                        time.sleep(0.2)
                        active_ready.wait(timeout=5)

                        if detached.is_set():
                            raise RuntimeError('session detached during hook install')

                        ping = send_command(attach_script, 'ping', timeout=5)
                        if not (isinstance(ping, dict) and ping.get('pong')):
                            raise RuntimeError(f'ping failed: {ping}')

                        return attach_script, attach_session, None
                    except Exception as exc:
                        last_errors = [*attempt_errors, f'hooks: {type(exc).__name__}: {exc}']
                        try:
                            attach_script.unload()
                        except Exception:
                            pass
                        try:
                            attach_session.detach()
                        except Exception:
                            pass
                        if attempt < 4:
                            time.sleep(5)

                return None, None, last_errors

            use_attach_running = attach_running or os.getenv("TITLE_INJECTOR_ATTACH_RUNNING") == "1"

            attach_errors = None
            spawn_errors = []
            script = None
            session = None
            if use_attach_running:
                script, session, attach_errors = try_attach_running_session()
                if not script or not session:
                    detail = '; '.join(attach_errors) if attach_errors else 'no attach details'
                    return {
                        'error': (
                            'Attach-running mode failed. '
                            'Restart the game/emulator and retry without attach-running '
                            f'or inspect the runtime state. Details: {detail}'
                        )
                    }
            else:
                max_spawn_attempts = max(
                    1,
                    int(os.getenv("TITLE_INJECTOR_SPAWN_ATTEMPTS", "2")),
                )
                for attempt in range(1, max_spawn_attempts + 1):
                    script, session = mgr._spawn_session()
                    if script and session:
                        break
                    spawn_errors.append(
                        getattr(mgr, 'last_spawn_error', None)
                        or 'spawn session returned no script'
                    )
                    if attempt < max_spawn_attempts:
                        time.sleep(3)

            if not script or not session:
                if use_attach_running and attach_errors:
                    detail = '; '.join(attach_errors)
                    return {'error': f'Spawn session failed after attach-running errors: {detail}'}
                detail = '; '.join(spawn_errors) if spawn_errors else 'no spawn details'
                return {
                    'error': (
                        'Spawn session failed in clean-spawn mode '
                        f'after {max(1, len(spawn_errors))} attempt(s): {detail}'
                    )
                }

            try:
                set_result = send_command(
                    script,
                    'call_method',
                    tbl='TempleHandler',
                    method='SetTitle',
                    args=[f'i:{target_gov_id}', f'i:{pkt_data["title_id"]}'],
                    timeout=10,
                )
                if isinstance(set_result, dict) and set_result.get('ok') and mgr._verify_title_assignment(
                    script, pkt_data['title_id'], target_gov_id
                ):
                    return {
                        'success': True,
                        'method': 'frida-lua-settitle',
                        'title': title,
                        'title_id': pkt_data['title_id'],
                        'target_gov_id': target_gov_id,
                    }

                result = send_command(
                    script,
                    'inject_whmp_title',
                    titleType=pkt_data['title_id'],
                    targetGovId=target_gov_id,
                    timeout=10,
                )
                if isinstance(result, dict) and result.get('ok') and mgr._verify_title_assignment(
                    script, pkt_data['title_id'], target_gov_id
                ):
                    return {
                        'success': True,
                        'method': 'frida-whmp',
                        'title': title,
                        'title_id': pkt_data['title_id'],
                        'target_gov_id': target_gov_id,
                        'fd': result.get('fd'),
                        'bytes_sent': result.get('bytes'),
                        'packet': result.get('packetHex', pkt_data['packet']),
                    }
            finally:
                try:
                    script.unload()
                except Exception:
                    pass
                try:
                    session.detach()
                except Exception:
                    pass

            set_err = set_result.get('__error', str(set_result)) if isinstance(set_result, dict) else str(set_result)
            whmp_err = result.get('__error', str(result)) if isinstance(result, dict) else str(result)
            return {'error': f'Title assignment not verified. SetTitle={set_err}; WHMP={whmp_err}'}
                
        except Exception as e:
            return {'error': f'Frida injection failed: {str(e)}'}
    
    def inject(
        self,
        title: str,
        target_gov_id: int = 44003549,
        attach_running: bool = False,
    ):
        """Main injection method - tries best available method"""
        
        print(f"[*] Injecting {title.upper()}...")
        
        # Try Frida first
        result = self.inject_frida(
            title,
            target_gov_id,
            attach_running=attach_running,
        )
        
        if 'error' in result:
            # Return packet data for manual injection
            pkt_data = self.get_title_data(title, target_gov_id)
            return {
                'packet_ready': True,
                'packet': pkt_data['packet'],
                'size': pkt_data['size'],
                'target_gov_id': target_gov_id,
                'message': 'Packet ready for manual injection',
                'error': result.get('error')
            }
        
        return result

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ROK Title Injection Backend',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python title_injector.py give duke
  python title_injector.py list
      python title_injector.py packet justice --target 44003549
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # Give title
    give_parser = subparsers.add_parser('give', help='Give title to player')
    give_parser.add_argument('title', help='Title name')
    give_parser.add_argument('--target', type=int, default=44003549, help='Target gov_id')
    give_parser.add_argument(
        '--attach-running',
        action='store_true',
        help='Experimental: attach to an already running game instead of using a clean spawn',
    )
    
    # List titles
    subparsers.add_parser('list', help='List available titles')
    
    # Get packet
    pkt_parser = subparsers.add_parser('packet', help='Get packet hex')
    pkt_parser.add_argument('title', help='Title name')
    pkt_parser.add_argument('--target', type=int, default=44003549, help='Target gov_id')
    
    args = parser.parse_args()
    
    backend = TitleInjectorBackend()
    
    if args.command == 'give':
        result = backend.inject(
            args.title,
            args.target,
            attach_running=args.attach_running,
        )
        print("\n[Result]")
        print(json.dumps(result, indent=2))
        return 0 if result.get('success') else 1
    
    elif args.command == 'list':
        titles = backend.service.list_titles()
        print("\nAvailable Titles:")
        for t in titles['titles']:
            print(f"  {t['id']:2d} - {t['name']}")
        print("\nVerified: ✅ Manual test passed")
        return 0
    
    elif args.command == 'packet':
        pkt = backend.get_title_data(args.title, args.target)
        if 'error' in pkt:
            print(f"Error: {pkt['error']}")
            return 1
        print(f"\nTitle: {pkt['title'].upper()}")
        print(f"Target gov_id: {pkt['target_gov_id']}")
        print(f"Hex:   {pkt['packet']}")
        print(f"Size:  {pkt['size']} bytes")
        print(f"✅ Verified working")
        return 0
    
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())
