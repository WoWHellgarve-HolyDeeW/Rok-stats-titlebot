import logging
import threading
from dummy_root import get_app_root
from roktracker.utils.check_python import check_py_version
from roktracker.utils.exception_handling import ConsoleExceptionHander
from roktracker.utils.output_formats import OutputFormats
from roktracker.utils.api_client import StatsHubAPIClient, APIConfig, load_api_config, save_api_config

logging.basicConfig(
    filename=str(get_app_root() / "kingdom-scanner.log"),
    encoding="utf-8",
    format="%(asctime)s %(module)s %(levelname)s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

check_py_version((3, 11))

import json
import questionary
import signal
import sys

from roktracker.kingdom.governor_printer import print_gov_state
from roktracker.kingdom.scanner import KingdomScanner
from roktracker.kingdom.governor_data import GovernorData
from roktracker.kingdom.additional_data import AdditionalData
from roktracker.utils.adb import *
from roktracker.utils.adb_lock import single_instance_lock
from roktracker.utils.console import console
from roktracker.utils.general import *
from roktracker.utils.ocr import get_supported_langs
from roktracker.utils.validator import sanitize_scanname, validate_installation

# Global API client for use in callbacks
api_client: StatsHubAPIClient | None = None


logger = logging.getLogger(__name__)
ex_handler = ConsoleExceptionHander(logger)


sys.excepthook = ex_handler.handle_exception
threading.excepthook = ex_handler.handle_thread_exception


def print_gov_and_upload(gov_data: GovernorData, extra: AdditionalData) -> None:
    """Callback that prints governor state and uploads to API."""
    # First, print the state
    print_gov_state(gov_data, extra)
    
    # Then, upload to API if enabled
    global api_client
    if api_client and api_client.config.auto_upload:
        gov_dict = {
            "ID": gov_data.id,
            "Name": gov_data.name,
            "Power": gov_data.power,
            "Killpoints": gov_data.killpoints,
            "Alliance": gov_data.alliance,
            "T1 Kills": gov_data.t1_kills,
            "T2 Kills": gov_data.t2_kills,
            "T3 Kills": gov_data.t3_kills,
            "T4 Kills": gov_data.t4_kills,
            "T5 Kills": gov_data.t5_kills,
            "Deads": gov_data.dead,
            "Rss Gathered": gov_data.rss_gathered,
            "Rss Assistance": gov_data.rss_assistance,
            "Helps": gov_data.helps,
        }
        api_client.add_governor(gov_dict)


def ask_abort(kingdom_scanner: KingdomScanner) -> None:
    stop = questionary.confirm(
        message="Do you want to stop the scanner?:", auto_enter=False, default=False
    ).ask()

    if stop:
        console.print("Scan will aborted after next governor.")
        kingdom_scanner.end_scan()


def ask_continue(msg: str) -> bool:
    return questionary.confirm(message=msg, auto_enter=False, default=False).ask()


def main():
    if not validate_installation().success:
        sys.exit(2)
    root_dir = get_app_root()

    try:
        config = load_config()
    except ConfigError as e:
        logger.fatal(str(e))
        console.log(str(e))
        sys.exit(3)

    scan_options = {
        "ID": False,
        "Name": False,
        "Power": False,
        "Killpoints": False,
        "Alliance": False,
        "T1 Kills": False,
        "T2 Kills": False,
        "T3 Kills": False,
        "T4 Kills": False,
        "T5 Kills": False,
        "Ranged": False,
        "Deads": False,
        "Rss Assistance": False,
        "Rss Gathered": False,
        "Helps": False,
    }

    console.print(
        "Tesseract languages available: "
        + get_supported_langs(str(root_dir / "deps" / "tessdata"))
    )

    try:
        bluestacks_device_name = questionary.text(
            message="Name of your bluestacks instance:",
            default=config["general"]["bluestacks"]["name"],
        ).unsafe_ask()

        bluestacks_port = int(
            questionary.text(
                f"Adb port of device (detected {get_bluestacks_port(bluestacks_device_name, config)}):",
                default=str(get_bluestacks_port(bluestacks_device_name, config)),
                validate=lambda port: is_string_int(port),
            ).unsafe_ask()
        )

        kingdom = questionary.text(
            message="Kingdom name (used for file name):",
            default=config["scan"]["kingdom_name"],
        ).unsafe_ask()

        validated_name = sanitize_scanname(kingdom)
        while not validated_name.valid:
            kingdom = questionary.text(
                message="Kingdom name (Previous name was invalid):",
                default=validated_name.result,
            ).unsafe_ask()
            validated_name = sanitize_scanname(kingdom)

        scan_amount = int(
            questionary.text(
                message="Number of people to scan:",
                validate=lambda port: is_string_int(port),
                default=str(config["scan"]["people_to_scan"]),
            ).unsafe_ask()
        )

        resume_scan = questionary.confirm(
            message="Resume scan:",
            auto_enter=False,
            default=config["scan"]["resume"],
        ).unsafe_ask()

        new_scroll = questionary.confirm(
            message="Use advanced scrolling method:",
            auto_enter=False,
            default=config["scan"]["advanced_scroll"],
        ).unsafe_ask()
        config["scan"]["advanced_scroll"] = new_scroll

        track_inactives = questionary.confirm(
            message="Screenshot inactives:",
            auto_enter=False,
            default=config["scan"]["track_inactives"],
        ).unsafe_ask()

        scan_mode = questionary.select(
            "What scan do you want to do?",
            choices=[
                questionary.Choice(
                    "Full (Everything the scanner can)",
                    value="full",
                    checked=True,
                    shortcut_key="f",
                ),
                questionary.Choice(
                    "Seed (ID, Name, Power, KP, Alliance)",
                    value="seed",
                    checked=False,
                    shortcut_key="s",
                ),
                questionary.Choice(
                    "Custom (select needed items in next step)",
                    value="custom",
                    checked=False,
                    shortcut_key="c",
                ),
            ],
        ).unsafe_ask()

        match scan_mode:
            case "full":
                scan_options = {
                    "ID": True,
                    "Name": True,
                    "Power": True,
                    "Killpoints": True,
                    "Alliance": True,
                    "T1 Kills": True,
                    "T2 Kills": True,
                    "T3 Kills": True,
                    "T4 Kills": True,
                    "T5 Kills": True,
                    "Ranged": True,
                    "Deads": True,
                    "Rss Assistance": True,
                    "Rss Gathered": True,
                    "Helps": True,
                }
            case "seed":
                scan_options = {
                    "ID": True,
                    "Name": True,
                    "Power": True,
                    "Killpoints": True,
                    "Alliance": True,
                    "T1 Kills": False,
                    "T2 Kills": False,
                    "T3 Kills": False,
                    "T4 Kills": False,
                    "T5 Kills": False,
                    "Ranged": False,
                    "Deads": False,
                    "Rss Assistance": False,
                    "Rss Gathered": False,
                    "Helps": False,
                }
            case "custom":
                items_to_scan = questionary.checkbox(
                    "What stats should be scanned?",
                    choices=[
                        questionary.Choice(
                            "ID",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Name",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Power",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Killpoints",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Alliance",
                            checked=False,
                        ),
                        questionary.Choice(
                            "T1 Kills",
                            checked=False,
                        ),
                        questionary.Choice(
                            "T2 Kills",
                            checked=False,
                        ),
                        questionary.Choice(
                            "T3 Kills",
                            checked=False,
                        ),
                        questionary.Choice(
                            "T4 Kills",
                            checked=False,
                        ),
                        questionary.Choice(
                            "T5 Kills",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Ranged",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Deads",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Rss Assistance",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Rss Gathered",
                            checked=False,
                        ),
                        questionary.Choice(
                            "Helps",
                            checked=False,
                        ),
                    ],
                ).unsafe_ask()
                if items_to_scan == [] or items_to_scan == None:
                    console.print("Exiting, no items selected.")
                    return
                else:
                    for item in items_to_scan:
                        scan_options[item] = True
            case _:
                console.print("Exiting, no mode selected.")
                return

        validate_kills = False
        reconstruct_fails = False

        if (
            scan_options["T1 Kills"]
            and scan_options["T2 Kills"]
            and scan_options["T3 Kills"]
            and scan_options["T4 Kills"]
            and scan_options["T5 Kills"]
            and scan_options["Killpoints"]
        ):
            validate_kills = questionary.confirm(
                message="Validate killpoints:",
                auto_enter=False,
                default=config["scan"]["validate_kills"],
            ).unsafe_ask()

        if validate_kills:
            reconstruct_fails = questionary.confirm(
                message="Try reconstructiong wrong kills values:",
                auto_enter=False,
                default=config["scan"]["reconstruct_kills"],
            ).unsafe_ask()

        validate_power = questionary.confirm(
            message="Validate power (only works in power ranking):",
            auto_enter=False,
            default=config["scan"]["validate_power"],
        ).unsafe_ask()

        power_threshold = int(
            questionary.text(
                message="Power threshold to trigger warning:",
                validate=lambda pt: is_string_int(pt),
                default=str(config["scan"]["power_threshold"]),
            ).unsafe_ask()
        )

        config["scan"]["timings"]["info_close"] = float(
            questionary.text(
                message="Time to wait after more info close:",
                validate=lambda port: is_string_float(port),
                default=str(config["scan"]["timings"]["info_close"]),
            ).unsafe_ask()
        )

        config["scan"]["timings"]["gov_close"] = float(
            questionary.text(
                message="Time to wait after governor close:",
                validate=lambda port: is_string_float(port),
                default=str(config["scan"]["timings"]["gov_close"]),
            ).unsafe_ask()
        )

        save_formats = OutputFormats()
        save_formats_tmp = questionary.checkbox(
            "In what format should the result be saved?",
            choices=[
                questionary.Choice(
                    "Excel (xlsx)",
                    value="xlsx",
                    checked=config["scan"]["formats"]["xlsx"],
                ),
                questionary.Choice(
                    "Comma seperated values (csv)",
                    value="csv",
                    checked=config["scan"]["formats"]["csv"],
                ),
                questionary.Choice(
                    "JSON Lines (jsonl)",
                    value="jsonl",
                    checked=config["scan"]["formats"]["jsonl"],
                ),
            ],
        ).unsafe_ask()

        if save_formats_tmp == [] or save_formats_tmp == None:
            console.print("Exiting, no formats selected.")
            return
        else:
            save_formats.from_list(save_formats_tmp)

        # API Upload configuration
        global api_client
        api_config_path = root_dir / "api_config.json"
        api_config = load_api_config(api_config_path)
        
        enable_api_upload = questionary.confirm(
            message="Upload scan data to Stats Hub API (real-time):",
            auto_enter=False,
            default=api_config.auto_upload,
        ).unsafe_ask()

        if enable_api_upload:
            api_url = questionary.text(
                message="API URL:",
                default=api_config.base_url,
            ).unsafe_ask()

            # Try to extract kingdom number from the kingdom name
            default_kd = api_config.kingdom_number
            try:
                # Try to parse kingdom number from the name (e.g., "3328" or "kd3328")
                import re
                kd_match = re.search(r'(\d{4})', kingdom)
                if kd_match:
                    default_kd = int(kd_match.group(1))
            except:
                pass

            kingdom_number = int(
                questionary.text(
                    message="Kingdom number (for API):",
                    validate=lambda x: is_string_int(x),
                    default=str(default_kd) if default_kd else "",
                ).unsafe_ask()
            )

            api_config = APIConfig(
                base_url=api_url.rstrip('/'),
                kingdom_number=kingdom_number,
                auto_upload=True,
                batch_size=5,  # Send every 5 governors
            )
            
            # Test connection
            api_client = StatsHubAPIClient(api_config)
            api_client.set_status_callback(lambda msg: console.print(msg))
            
            if api_client.test_connection():
                console.print("[green]API connection successful![/green]")
                save_api_config(api_config, api_config_path)
            else:
                console.print("[yellow]WARN: API not reachable. Continuing without upload.[/yellow]")
                api_config.auto_upload = False
                api_client = None
        else:
            api_client = None

    except:
        console.log("User abort. Exiting scanner.")
        sys.exit(3)

    try:
        lock_name = f"rok_ui_localhost:{bluestacks_port}"
        with single_instance_lock(lock_name, timeout_s=0.0) as acquired:
            if not acquired:
                console.print(
                    f"[red]ERROR: Outro bot/scanner já está a controlar este emulador (lock: {lock_name}).[/red]"
                )
                console.print(
                    "[yellow]Feche o Title Bot/Remote Bot (ou use outro BlueStacks/porta) e tente de novo.[/yellow]"
                )
                return

        kingdom_scanner = KingdomScanner(config, scan_options, bluestacks_port)
        kingdom_scanner.set_continue_handler(ask_continue)
        kingdom_scanner.set_governor_callback(print_gov_and_upload)

        console.print(
            f"The UUID of this scan is [green]{kingdom_scanner.run_id}[/green]",
            highlight=False,
        )
        
        if api_client and api_client.config.auto_upload:
            console.print(
                f"[cyan]Real-time upload enabled to {api_client.config.base_url} (KD {api_client.config.kingdom_number})[/cyan]",
                highlight=False,
            )

        signal.signal(signal.SIGINT, lambda _, __: ask_abort(kingdom_scanner))

            kingdom_scanner.start_scan(
                kingdom,
                scan_amount,
                resume_scan,
                track_inactives,
                validate_kills,
                reconstruct_fails,
                validate_power,
                power_threshold,
                save_formats,
            )

            # Finalize API upload
            if api_client and api_client.config.auto_upload:
                console.print("[cyan]Finalizing API upload...[/cyan]")
                api_client.finalize()
                console.print(f"[green]Total governors uploaded: {api_client.total_sent}[/green]")

    except AdbError as error:
        logger.error(
            "An error with the adb connection occured (probably wrong port). Exact message: "
            + str(error)
        )
        console.print(
            "An error with the adb connection occured. Please verfiy that you use the correct port.\nExact message: "
            + str(error)
        )


if __name__ == "__main__":
    main()
    input("Press enter to exit...")
