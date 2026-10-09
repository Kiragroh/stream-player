"""PyInstaller entry point for the native Windows application."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from stream_player.desktop import main
    raise SystemExit(main())
