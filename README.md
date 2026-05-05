# Rotunda

Giving your Agents the power to browse the web is like giving them superpowers. You can automate almost anything. Rotunda is a browser built for Agents from the ground up. Sick of seeing more captchas and roadblocks than when you open Chrome and do it yourself? Try Rotunda.

## Getting Started

```python
TODO
```

## On stealth browsing

Web automation is incredible. Unfortunately for us, so many people have abused the automation powers of browsers in the past (ticket scalpers, shoe resellers) that sites have poured billions into detecting anything that's not a human. If you run Chrome over CDP with Playwright you'll know what I'm talking about. You get recaptchas, refusals to login, or subtle changes in behavior.

"Stealth" plugins advertise that they're able to evade these detections. But all stealth plugins are flawed. They often rely on overriding Javascript properties to return fake values that simulate another browser. Fingerprinters will check if these function implementations are native or non-native. Non-native never happens in the wild so you're flagged as a bot. Other plugins will fork Chromium and patch code that do the same things on the backend, so you'll be unable to detect them by sniffing Javascript state. Fingerprinters then use browser accessories like the canvas or audio drivers to detect anomalies with known devices. And so you're flagged as a bot. And on and on.

This cat and mouse game has been around since the beginning of the web. As fingerprinting has switched from adhoc to statistical, the burden has shifted dramatically to the stealth implementers. Our view at Rotunda is it's _impossible to compellingly lie about your browser fingerprint_. In the law of large numbers, and the surface area of APIs that browsers have to support, there's some way to detect that you're anomalous. The sites only need one thing wrong to prove that you're faking your whole identity. You need to patch every surface area, simulate the subtleties of every GPU driver, and honestly it's just not a game worth playing.

Instead Rotunda focuses on providing a browser that looks fully human, without lying about its underlying identity. We _want_ to look like it's actually running on your laptop - and instead focus on making sure no automation signatures can be detected. This includes making sure that Playwright can't be detected as the driver controlling your screen, and that any mouse movements tween as if, and that keyboard clicks have some occasional errors. Instead of lying about your fingerprint it's better to fib: tell them what GPU and audio drivers you're running on, but lie about some specifics like accessible fonts or extensions or screen size. It's not out of the ordinary for 10 M1 chips to be browsing their site at the same time.

This results in a browser that's not suitable for crawling. For public sites you should be automating that in the cloud anyway via [Browserbase](https://browserbase.com/), [Kernel](https://kernel.sh/), or [ScrapingBee](https://www.scrapingbee.com/). But it's _very_ suitable when you're delegating tasks to your Agents. It's like having a fleet of interns that are doing useful work on your home network.

## Fingerprint Blocked?

You're a lot less likely to get flagged as a bot with our host-passthrough approach. But that doesn't mean it's impossible. First we recommend you open the same site in Chrome/Firefox and see if you still start seeing flags. If you do it might be because of your IP reputation.

If other browsers work fine and you suspect it's at the Rotunda level, run the same site with our debugging handlers. This echos the calls that the site makes into the Javascript VM, the return values from those calls, console output, and outgoing page requests sent to their servers. 99.99% of the time these payloads reveal that the site picked up on something anomalous. The only thing they don't really cover is the TCP handshake, but we're using the authentic Firefox protocol for that anyway.

```sh
export ROTUNDA_DEBUG_DUMP_DIR=/tmp/rotunda-fingerprint-debug
export ROTUNDA_DEBUG_DUMP=manifest,network,console,vm,returns
export ROTUNDA_VM_ACCESS_SAMPLE_RATE=10

python your_repro_script.py
zip -r rotunda-fingerprint-debug.zip "$ROTUNDA_DEBUG_DUMP_DIR"
```

Attach `rotunda-fingerprint-debug.zip` to a GitHub Issue with the site URL, what you expected to happen, and what the site reported instead. The dump includes request/response bodies, so review it before sharing and do not set `ROTUNDA_DEBUG_DUMP_RAW=1` unless a maintainer asks for it.

## Want to help?

There are a ton of ways to get involved. Check the Issues for any good getting started tickets and chime that you're interested in helping out. Also hit me up on [X](https://x.com/piercefreeman) or subscribe to my [newsletter](https://pierce.dev/media) if you want to chat about agents and support the development.

## Credits

This repository builds on daijro's original Firefox patching work, which laid the foundation - via much trial and error - for the browser patching techniques used here. They made the case for using Firefox because Juggler is isolated from the browser context (unlike CDP).

Their main focus, however, is on stealth whereas ours is on automation. We want to give your Agents access to a browser that works almost identically to your daily driver.

- Repository: [github.com/piercefreeman/rotunda](https://github.com/piercefreeman/rotunda)
- Docs: [rotunda.com](https://rotunda.com)

## FAQ

Can't I just control Chrome with computer vision?

You certainly can try! Computer vision isn't a perfect answer here because it's so slow, fills up your context window, and doesn't allow your agent to see any content that's not in the viewport. It's much more convenient to grab the current DOM and parse it into an LLM friendly representation of the page. But grabbing this representation opens you up to the same question of Playwright/CDP control that we were trying to avoid.

Launching in most cloud VMs to use computer vision also risks leaking state about the underlying host. Most use the same stealth plugins that are pretty easy to detect, which means you're going to eventually get flagged if you use them naturally.

Plus computer vision sometimes makes it hard to click around some websites because direct click events are hard to translate cleanly (see reports of Claude being unable to select dropdowns from form lists).
