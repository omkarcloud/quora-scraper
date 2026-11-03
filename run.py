"""Start the Quora Scraper API.

    python run.py            # http://localhost:8000
    PORT=9000 python run.py  # another port

Then:  curl "http://localhost:8000/questions/answers?question=What-is-it-like-to-work-at-SpaceX"
"""
import bottle
from cheroot import wsgi

import config
import routes  # noqa: F401  (mounts the routes on bottle's default app)


def main():
    app = bottle.default_app()
    print(f"Quora Scraper listening on http://localhost:{config.PORT}/")
    print(f"Try:  curl \"http://localhost:{config.PORT}/questions/answers?question=What-is-it-like-to-work-at-SpaceX\"")
    server = wsgi.Server(("0.0.0.0", config.PORT), app, server_name="quora-scraper", numthreads=16)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
