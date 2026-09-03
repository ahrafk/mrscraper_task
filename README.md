# Lowe's PDP Scraper

A REST API that scrapes Lowe's product detail pages and returns the fully rendered HTML with the live price sitting in it. Built specifically to survive Akamai Bot Manager, the anti scraping protection Lowe's runs behind.

Live API: https://lowes-pdp-scraper.onrender.com

Example request:

GET https://lowes-pdp-scraper.onrender.com/lowes?productUrl=https://www.lowes.com/pd/Amana-Amana-Dishwasher-with-Dark-Interior/5015745545&format=json

## The short version of what this is

The scraping logic itself was never the hard part here, getting past Akamai was. A full day of testing showed that the usual approach, residential proxies plus browser automation, gets blocked close to 100% of the time against this specific site, no matter how good the fingerprint is or which proxy provider is used. What actually works reliably is architecturally different from a typical scraper. Real Android phones, on real mobile carrier connections, render the page in a real mobile browser, and the results get relayed back to this server over a websocket. Nothing about the browser identity is faked because none of it is simulated, it's a genuine phone doing genuine browsing.

This is built using Python and FastAPI.

## Setup instructions

Clone the repo and set up a virtual environment.

```
git clone https://github.com/ahrafk/mrscraper_task.git
cd mrscraper_task
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in .env with at least PHONE_RELAY_TOKEN. If you'd rather not install Python directly on your machine, there's a Dockerfile that handles all of that for you.

```
docker build -t lowes-pdp-scraper .
docker run --env-file .env -p 3000:3000 lowes-pdp-scraper
```

The container only needs the server side running. The phone itself connects out to whatever public URL this container is deployed behind, it never needs to reach the container directly.

## Run and test instructions

Once .env is filled in and at least one phone is connected, start the server with either of these.

```
python -m app
uvicorn app.main:app --reload --port 3000
```

Then hit it with curl.

```
curl "http://localhost:3000/lowes?productUrl=https://www.lowes.com/pd/{slug}/{id}"
```

For load testing, two scripts live in the scripts folder. harvest_urls.py crawls Lowe's search result pages through the deployed API and pulls out real distinct product URLs, useful for building a test set. load_test.py fires concurrent requests at the live API and reports success rate, error rate, and latency percentiles, writing a JSON report at the end.

```
python scripts/harvest_urls.py
python scripts/load_test.py
```

## How the scraper actually works

This scrapes by rendering the page on a real physical Android phone, inside a real WebView, over that phone's real cellular connection, then relaying the finished HTML back to this server over a websocket. There's no fingerprint to spoof because nothing is simulated at all, it's simply a phone browsing the internet the way a phone normally does.

Earlier approaches were tried and ruled out along the way, worth mentioning honestly since a lot of them didn't work and that history shaped the final design. Chromium through a residential proxy pool got blocked before any bot detection script even finished running. Camoufox, a hardened version of Firefox with anti detection patches built in, looked promising at first, then degraded to near zero success over sustained testing. Careful checking of our own fingerprint consistency found and fixed a real Firefox version mismatch and a timezone leak, but fixing those didn't change the block rate at all, which pointed at something above the JavaScript challenge layer entirely, likely a reputation or behavioral signal rather than a static fingerprint check. Testing residential IPs from five different countries through the same proxy pool made no difference either. Even routing through a real phone's cellular IP while still spoofing a desktop browser identity still got blocked, which showed that IP quality alone isn't enough, a mismatch between a mobile carrier IP and a desktop user agent is itself a signal worth flagging. Only once the browser identity stopped being spoofed entirely, real phone, real mobile IP, real WebView, did things actually start working, with a first clean test coming back at zero errors. Those earlier approaches were removed from this codebase once the working approach was confirmed, so what you'll find here is only the real phone rendering path, not the abandoned experiments.

A few concrete things this system does to avoid detection and keep things stable. Every request goes through a randomized delay before it fires, so requests don't land at mechanically regular intervals. Concurrency is capped to however many phones are actually connected at that moment, and this scales automatically as phones connect or disconnect, nothing needs to be manually adjusted. Any phone that returns a page recognized as a block gets set aside for a few minutes before it's used again, and a phone that stops responding twice in a row gets treated as unresponsive and pulled from rotation too, so one bad or flagged device can't keep dragging every request down with it while the rest of the fleet keeps working normally.

One more piece worth describing since it's a real part of the anti detection strategy. Rather than navigating a phone's browser directly to the exact product URL, which is a pattern real users basically never produce, the app first runs a search using terms derived from the product's own URL slug, waits a moment like someone actually reading the results, and then clicks through to the matching product the way a person would. If the search results don't contain an exact match, or if this whole flow fails for any reason, it falls back to loading the product page directly, so correctness is never sacrificed even when the more realistic path doesn't work out.

On the proxy side, a straightforward residential proxy service was tested thoroughly early on and found to be blocked close to 100 percent of the time against this target regardless of technique, documented here as a real finding from real testing rather than something quietly worked around.

A response only counts as a real success if it isn't a recognized block page and the price is actually extractable from the rendered HTML, either from Lowe's own structured price field or a regex fallback against the visible markup. There's also a check that the landed page's product id actually matches the one that was requested, since a redirect to the wrong page or the homepage should never be counted as a success even if the response looks otherwise fine.

## Honest current state and known limitations

This depends on physical phones staying connected, charged, and not killed by the phone's own battery optimization, which is a real operational dependency a pure cloud deployment wouldn't have. Several real reliability issues were found and fixed along the way, a race condition that could crash the app mid render, a resource leak on reconnect, and a case where the phone's own background restart logic silently failed to recover its configuration after being killed by the OS.

The most recent full test run, 200 requests at a matched concurrency of four phones, came back at 79 percent success and 21 percent error, with zero blocking related failures the entire run, every failure was a timeout or a capacity issue rather than a detection issue. Average latency was about 31 seconds, comfortably under the 60 second target, though the tail end did reach close to 60 seconds under contention. This is documented honestly rather than rounded up, along with the fact that the render timeout budget has since been increased specifically to address the pattern seen in that run, since renders were sometimes genuinely needing more time than was being reserved for them.
