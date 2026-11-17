import socket
import threading
import time
import webbrowser
import uvicorn


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', 8000))
    except OSError:
        sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    config = uvicorn.Config('app:app', host='127.0.0.1', port=port, log_level='warning')
    server = uvicorn.Server(config)
    def open_when_ready():
        while not server.started and not server.should_exit:
            time.sleep(.1)
        if server.started:
            webbrowser.open(f'http://127.0.0.1:{port}/')
    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f'Программа работает: http://127.0.0.1:{port}/\nДля завершения нажмите Ctrl+C.')
    server.run(sockets=[sock])

if __name__ == '__main__':
    main()
