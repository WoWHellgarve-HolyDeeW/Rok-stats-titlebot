import frida, time, traceback
try:
    print("Getting device...", flush=True)
    d = frida.get_usb_device(5)
    print(f"Device: {d}", flush=True)
    
    print("Attaching...", flush=True)
    s = d.attach(5500)
    print("Attached!", flush=True)
    
    print("Creating script...", flush=True)
    scr = s.create_script('send(42)')
    print("Created!", flush=True)
    
    scr.on('message', lambda m, d: print(f"MSG: {m}", flush=True))
    scr.load()
    print("Loaded!", flush=True)
    
    time.sleep(2)
    scr.unload()
    s.detach()
    print("Done!", flush=True)
except Exception as e:
    traceback.print_exc()
    print(f"Error: {e}", flush=True)
