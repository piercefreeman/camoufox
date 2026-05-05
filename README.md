# Cadence

Giving your Agents the power to browse the web is like giving them superpowers. You can automate almost anything. Cadence is a browser built for Agents from the ground up. Sick of seeing more captchas and roadblocks than when you open Chrome and do it yourself? Try Cadence.

## Browser

Web automation is incredible. Unfortunately for us, so many people have abused the automation powers of browsers in the past (ticket scalpers, shoe resellers) that sites have poured billions into detecting anything that's not a human. If you run Chrome over CDP with Playwright you'll know what I'm talking about.

"Stealth" plugins advertise that they're able to evade these detections. But all stealth plugins are flawed. They either rely on overriding Javascript properties to return fake values that simulate another browser. But these are easily detected by the site checking if these function codes are native or non-native. Non-native raises a flag. So then plugins will fork Chromium and patch code that do the same things on the backend, so. Fingerprinters start using browser accessories like the canvas or audio drivers to detect anomalies.

This cat and mouse game has been around since the beginning of the web. As fingerprinting has switched from adhoc to statistical, the burdeon has shifted dramatically to the stealth implementers. Our view at Cadence is it's _impossible to compellingly lie about your fingerprint_. In the law of large numbers, and the surface area of APIs that browser have to support, there's some way to detect that you're anomalous. The sites only need one thing wrong to prove that you're faking your whole identity. You need to patch every surface area, simulate the subtleties of every GPU driver, and honestly it's just not a game worth playing.

Instead Cadence focuses on providing a browser that looks fully human, without lying about its underlying identity. We _want_ to look like it's actually running on your laptop - and instead focus on making sure no automation signatures can be detected. This includes making sure that Playwright can't be detected as the driver controlling your screen, and that any mouse movements tween as if, and that keyboard clicks have some occasional errors.

This results in a browser that's not suitable for crawling. For public sites you should be automating that in the cloud anyway via [Browserbase](https://browserbase.com/), [Kernel](https://kernel.sh/), or [ScrapingBee](https://www.scrapingbee.com/). But it's _very_ suitable when you're delegating tasks to your Agents. It's like having a fleet of interns that are doing things on your home network.

## Fingerprint Blocked?

If you've been flagged as a bot.

## Credits

This repository is a fork of the original [daijro/camoufox](https://github.com/daijro/camoufox). camoufox laid the foundation - via much trial and error - for the stealth techniques used here. They made the case for using Firefox because Juggler is isolated from the browser context unlike CDP.

This fork is focused more on automation than it is on crawling; it gives your Agents access to a browser that works almost identically to your daily driver.

- Original project: [github.com/daijro/camoufox](https://github.com/daijro/camoufox)
- Upstream docs: [camoufox.com](https://camoufox.com)
- Python package code in this repo: [pythonlib/README.md](pythonlib/README.md)

## FAQ

Can't I just control Chrome with computer vision?

You certainly can try! Computer vision isn't a perfect answer here because it's so slow, fills up your context window, and doesn't allow your agent to see any content that's not in the viewport. It's much more convenient to grab the current DOM and parse it into an LLM friendly representation of the page. But grabbing this representation opens you up to the same question of Playwright/CDP control that we were trying to avoid.

Launching in most cloud VMs to use computer vision also risks leaking state about the underlying host. Most use the same stealth plugins that are pretty easy to detect, which means you're going to eventually get flagged if you use them naturally.

Plus computer vision sometimes makes it hard to click around some websites because direct click events are hard to translate cleanly (see reports of Claude being unable to select dropdowns from form lists).
