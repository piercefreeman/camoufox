# Firefox 150 Migration TODOs

Target: migrate Camoufox from Firefox 146.0.1 to Firefox 150.0.1 while keeping the browser standards-compliant and preventing newly introduced APIs from leaking inconsistent or host-identifying entropy.

Current repo base:

- `upstream.sh`: `version=146.0.1`, `release=beta.25`
- Source tree: `camoufox-146.0.1-beta.25`
- Source tarball: `firefox-146.0.1.source.tar.xz`

Target upstream:

- Firefox 150.0.1 source archive: `https://archive.mozilla.org/pub/firefox/releases/150.0.1/source/firefox-150.0.1.source.tar.xz`

## Migration Policy

- Prefer standards-compliant spoofing over disabling APIs.
- Temporarily disable a new high-entropy API only when the spoofing layer is not implemented yet.
- Every exposed identity-bearing value must come from the runtime fingerprint profile, an explicit policy, or a deterministic seed.
- Avoid implicit host reads. If Firefox can observe local hardware, OS services, local network state, display capabilities, installed models, or credential devices, Camoufox must either mask it or make it deterministic.
- Schema changes must land before browser patch code depends on new profile fields.
- Tests must cover page, iframe, dedicated worker, shared worker, and service worker exposure where the API is available in those globals.

## Profile Schema Notes

This checkout does not contain `.proto` files. The runtime profile contract is currently:

- `schemas/camoufox-profile.openapi.yaml`
- Generated Python model: `pythonlib/camoufox/_generated_profile.py`
- Generated C++ models: `additions/camoucfg/generated/profile/camoucfg/*`

TODO:

- [ ] Treat `schemas/camoufox-profile.openapi.yaml` as the protobuf-equivalent source of truth for this migration.
- [ ] For every new spoofed surface, add explicit schema fields or seed fields before writing Firefox patch code.
- [ ] Run `make generate-openapi` after schema edits.
- [ ] Update `example/fingerprint.json` and run `make validate-fingerprint-example`.
- [ ] Add Python pipeline tests proving generated fingerprints include coherent Firefox 150 values.

## Phase 0: Rebase Existing Patch Stack First

This is the first gating item. Do not implement new Firefox 150 feature spoofing until the existing 146 patch stack applies cleanly to 150 or each conflict has a tracked owner.

TODO:

- [ ] Update migration target metadata locally to Firefox 150.0.1 for verification without committing the version bump until patches pass.
- [x] Fetch or cache `firefox-150.0.1.source.tar.xz`.
- [x] Run fast patch verification against 150:

  ```sh
  CAMOUFOX_FIREFOX_VERSION=150.0.1 uv run scripts/verify_firefox_patches.py --skip-syntax --keep-workdir
  ```

- [x] Record every patch application failure in this file with file paths and reject paths.
- [x] Rebase current patches in application order until `verify_firefox_patches.py --skip-syntax` passes.
- [x] Run the verifier with compile-backed syntax checks once a Firefox 150 build or compile-command context exists.
- [x] Run `make setup` or `make dir` with `CAMOUFOX_FIREFOX_VERSION=150.0.1` after patch application passes.
- [x] Build Firefox 150 Camoufox at least once on the primary target.
- [ ] Run `make lint`.
- [ ] Run build-tester, service-tester, and Playwright suites against the 150 binary.
- [ ] Update docs and examples that hard-code `ff_version="146"` or paths containing `camoufox-146.0.1-beta.25`.

Patch groups that must be verified for source drift:

- [ ] Runtime profile/config infrastructure: `config.patch`, `fingerprint-injection.patch`, `cross-process-storage.patch`, `browser-init.patch`, `chromeutil.patch`
- [ ] Navigator identity: `navigator-spoofing.patch`
- [ ] Screen/window/document geometry: `screen-spoofing.patch`
- [ ] Canvas/audio entropy: `audio-context-spoofing.patch`, `audio-fingerprint-manager.patch`
- [ ] WebGL identity: `webgl-spoofing.patch`
- [ ] Fonts: `font-list-spoofing.patch`, `anti-font-fingerprinting.patch`, `font-hijacker.patch`
- [ ] Locale/timezone/geolocation: `locale-spoofing.patch`, `timezone-spoofing.patch`, `geolocation-spoofing.patch`
- [ ] Media devices/speech/WebRTC: `media-device-spoofing.patch`, `speech-voices-spoofing.patch`, `voice-spoofing.patch`, `webrtc-ip-spoofing.patch`
- [ ] Network and data exfil controls: `network-patches.patch`, LibreWolf network/privacy patches
- [ ] Playwright/Juggler integration: `patches/playwright/*.patch`, `additions/juggler/**`
- [ ] macOS and Windows platform patches

Firefox 150 patch-application baseline:

- [x] Current 146 control verifier passes against `firefox-146.0.1.source.tar.xz`.
- [x] Firefox 150 verifier runs against `/private/tmp/camoufox-firefox-source/firefox-150.0.1.source.tar.xz`.
- [x] Firefox 150 full stack applies cleanly with `--skip-syntax`.
- [x] First blocker resolved: `patches/playwright/0-playwright.patch` applies cleanly to a fresh Firefox 150.0.1 prepared workspace.
- [x] Firefox 150 verifier after rebasing `0-playwright.patch`: 12 patch blockers remained.
- [x] Firefox 150 verifier after rebasing through `geolocation-spoofing.patch`: 7 patch blockers remained.
- [x] Firefox 150 final patch-application verifier passed against `/private/tmp/camoufox-firefox-source/firefox-150.0.1.source.tar.xz`.
- [x] `CAMOUFOX_FIREFOX_VERSION=150.0.1 make dir` completed and created `camoufox-150.0.1-beta.25/_READY`.
- [x] Generated Firefox 150 source tree contains no `.rej` files after normal patch application.
- [x] Full verifier without `--skip-syntax` re-applied all 49 patches and reported `Syntax checks passed`.
- [x] After adding `patches/zz-display-media-features.patch`, full verifier re-applied all 50 patches and reported `Syntax checks passed`; compile-backed checks were still skipped because no compile-command context exists.
- [x] Re-ran `CAMOUFOX_FIREFOX_VERSION=150.0.1 make dir` after adding `patches/zz-display-media-features.patch`; normal source-tree patch application completed and recreated `_READY`.
- [x] Generated Firefox 150 source tree still contains no `.rej` files after the 50-patch `make dir` run.
- [x] SSD build objdir is mounted at `/Volumes/CamoufoxBuild/camoufox-150.0.1-beta.25-obj`; local generated-tree `mozconfig` sets `MOZ_OBJDIR` there. This is intentionally not a tracked patch and must be recreated if `make dir` regenerates the source tree.
- [x] `CAMOUFOX_FIREFOX_VERSION=150.0.1 make build` completed successfully against the SSD objdir with `0 compiler warnings present`.
- [x] Built app smoke passed via `CAMOUFOX_FIREFOX_VERSION=150.0.1 ./mach run --version`, reporting `Camoufox Camoufox 150.0.1-beta.25`.
- [x] Direct `dist/bin/camoufox --version` is not a valid smoke invocation for this local objdir layout; it exits with `Couldn't load XPCOM`, while `mach run --version` launches the packaged app path under `dist/Camoufox.app`.
- [x] Post-build patch verifier passed all 50 patches with `--skip-syntax` using `/Volumes/CamoufoxBuild/camoufox-patch-verify-150-post-buildfix4`.
- [x] Compile-backed verifier was attempted using `/Volumes/CamoufoxBuild/camoufox-150.0.1-beta.25-obj/clangd/compile_commands.json`; patch application passed, but all 82 selected syntax targets were skipped because no cached compile command matched those files. Treat the successful full build as the authoritative compile validation for this phase.
- [ ] Inspect non-blocking `/usr/bin/patch` warnings from `fingerprint-injection.patch` and `patches/librewolf/mozilla_dirs.patch`: both patches applied with no rejects, but emitted `No such line ... ignoring`.

Post-build Firefox 150 compatibility fixes now tracked in patches:

- [x] `patches/locale-spoofing.patch`: moved `/camoucfg` before `/intl/icu_capi/bindings/cpp` in `intl/components/moz.build` `LOCAL_INCLUDES` to satisfy Firefox 150 backend ordering.
- [x] `patches/anti-font-fingerprinting.patch`: added `ListFontsVisibilityProvider::GetDocument()` because the patch makes `FontVisibilityProvider::GetDocument()` pure virtual.
- [x] `patches/playwright/0-playwright.patch`: added WebRTC override includes for `juggler/screencast`.
- [x] `patches/playwright/0-playwright.patch`: migrated screencast widget lookup from removed `nsView`/`nsViewManager` APIs to `PresShell::GetRootWidget()`.
- [x] `patches/playwright/0-playwright.patch`: migrated forced-offline lookup from `GetWorkerAssociatedBrowsingContext()` to Firefox 150 `GetAssociatedBrowsingContext()`.
- [x] `patches/playwright/0-playwright.patch`: updated `JugglerSendMouseEvent` pressure assignment to construct Firefox 150's optional pressure field.
- [x] `patches/playwright/0-playwright.patch`: restored and adapted `nsDOMWindowUtils::SendTouchEvent*` implementations for the Playwright IDL declarations, using Firefox 150 widget dispatch return types.

`patches/playwright/0-playwright.patch` rejects against Firefox 150.0.1:

- [x] `docshell/base/nsDocShell.cpp`
- [x] `docshell/base/nsDocShell.h`
- [x] `dom/base/nsContentUtils.cpp`
- [x] `dom/base/nsGlobalWindowOuter.cpp`
- [x] `dom/interfaces/base/nsIDOMWindowUtils.idl`
- [x] `dom/media/systemservices/video_engine/desktop_capture_impl.cc`
- [x] `dom/media/systemservices/video_engine/desktop_capture_impl.h`
- [x] `dom/webidl/Window.webidl`
- [x] `dom/workers/RuntimeService.h`
- [x] `services/settings/Utils.sys.mjs`
- [x] `widget/cocoa/NativeKeyBindings.mm`
- [x] `widget/nsGUIEventIPC.h`

Resolved Firefox 150 patch blockers:

- [x] `patches/anti-font-fingerprinting.patch`: removed stale duplicate include/no-op MathML hunks.
- [x] `patches/audio-fingerprint-manager.patch`: rebased `nsGlobalWindowInner.h` method insertion after `GetRegionalPrefsLocales` removal.
- [x] `patches/config.patch`: rebased root `moz.build` footer after new Firefox 150 `ai-agent-tools` docs tree.
- [x] `patches/font-hijacker.patch`: rebased `FontFace::Load` and `layout/style/moz.build` footer.
- [x] `patches/geolocation-spoofing.patch`: rebased network provider override onto Firefox 150 `fetchLocation`/Glean logging path.
- [x] `patches/librewolf/ui-patches/hide-default-browser.patch`: rebased for Firefox 150 settings groups and default-browser UI layout.
- [x] `patches/locale-spoofing.patch`: moved `/camoucfg` into Firefox 150's existing `intl/components/moz.build` `LOCAL_INCLUDES`.
- [x] `patches/macos-sdk-bootstrap-26.4.patch`: rebased from Firefox 150's macOS SDK 26.2 baseline to 26.4.
- [x] `patches/librewolf/mozilla_dirs.patch`: rebased native manifest directory handling after forced-legacy path changes.
- [x] `patches/screen-spoofing.patch`: rebased window declarations, `nsScreen.cpp` includes, and CSS device-size override placement.
- [x] `patches/webgl-spoofing.patch`: rebased WebGL renderer/vendor overrides onto Firefox 150 RFP renderer/vendor branches.
- [x] `patches/windows-theming-bug-modified.patch`: dropped obsolete `EXTRA_DEPS` manifest hunk; retained manifest branding and macOS asset guard.

Remaining Firefox 150 patch blockers:

- [x] None for patch application with `--skip-syntax`.
- [x] None for normal `make dir` patch application.

## Phase 1: Firefox 150 Pref and Config Hardening

These prefs should be reviewed before any new high-entropy feature is allowed to ship. Prefer explicit policy over disabling standards APIs by default.

TODO:

- [x] Add explicit defaults for listed new Safe Browsing surfaces in `settings/camoufox.cfg`:
  - `browser.safebrowsing.globalCache.enabled`
  - `browser.safebrowsing.realTime.enabled`
  - `browser.safebrowsing.realTime.simulation.enabled`
  - `browser.safebrowsing.realTime.simulation.force`
- [x] Audited Firefox 150 `StaticPrefList.yaml` and pinned additional simulation prefs:
  - `browser.safebrowsing.realTime.simulation.hitProbability`
  - `browser.safebrowsing.realTime.simulation.cacheTTLSec`
  - `browser.safebrowsing.realTime.simulation.negativeCacheEnabled`
  - `browser.safebrowsing.realTime.simulation.negativeCacheTTLSec`
  - `browser.safebrowsing.realTime.simulation.noiseEntryCount`
- [ ] Add explicit geolocation provider hardening:
  - `geo.provider.use_winrt=false`
  - pref added in `settings/camoufox.cfg`
  - verify Windows builds never invoke WinRT location when profile geolocation is configured
- [x] Add explicit Local Network Access policy in `settings/camoufox.cfg` without disabling LNA:
  - review `network.lna.enabled`
  - review `network.lna.etp.enabled`
  - review `network.lna.block_insecure_contexts`
  - review `network.lna.local-network-to-localhost.skip-checks`
  - review `network.socket.allowed_nonlocal_domains`
- [x] Add explicit HDR/color media-query profile fields without disabling native behavior by default:
  - `screen.colorGamut`
  - `screen.dynamicRange`
  - `screen.videoDynamicRange`
  - `patches/zz-display-media-features.patch` uses profile values when present and falls back to Firefox/native behavior when absent
- [ ] Decide whether HTML color input, HDR video rendering, and canvas/video color output need additional profile fields beyond media-query exposure.
- [ ] Decide explicit policy defaults for high-entropy future APIs without disabling standards APIs solely for entropy:
  - `dom.security.credentialmanagement.digital.enabled`
  - `dom.modelcontext.enabled`
  - `dom.reporting.enabled`
  - `dom.reporting.header.enabled`
- [ ] Review removed prefs from 146 and delete dead config entries only after confirming Firefox 150 ignores them safely.

## Phase 2: WebGPU

Risk: high for cross-signal consistency, not automatically high because it exposes real GPU facts. WebGPU can expose adapter identity, supported features, limits, shader/compiler behavior, backend differences, worker availability, and rendering/timing characteristics. Existing WebGL spoofing does not cover this surface.

Policy:

- [ ] Do not disable `dom.webgpu.enabled` by default solely because WebGPU exposes GPU entropy.
- [ ] Keep Firefox 150's WebGPU behavior available when the selected fingerprint policy is native/passthrough and the host platform is the truth source.
- [ ] Disable WebGPU only when a profile explicitly selects `disabled`/`unavailable`, or when an enabled synthetic profile would otherwise create an impossible contradiction that is not yet patched.
- [ ] Treat entropy as a bug only when it is unmodeled persistent identity, contradicts other exposed signals, or bypasses per-context policy.

Standards-compliant target:

- [ ] Keep WebGPU available where Firefox 150 would normally expose it and the selected fingerprint policy permits it.
- [ ] In native/passthrough mode, expose the actual host GPU class consistently with actual WebGL, OS, architecture, and Firefox behavior.
- [ ] In synthetic/spoofed mode, return realistic adapter capabilities that match the selected WebGL profile, OS, architecture, and Firefox version.
- [ ] Avoid returning impossible combinations such as Apple GPU WebGL renderer with Windows-only WebGPU limits.

Profile schema TODO:

- [ ] Add `webGpu` to `CamoufoxProfile` only if Firefox 150 exposes WebGPU in our supported builds or if BrowserForge needs to describe its policy.
- [ ] Add `webGpu.policy` with values such as `native`, `disabled`, `unavailable`, `spoofed`.
- [ ] Default generated fingerprints to `native` when the broader fingerprint strategy uses actual host GPU facts.
- [ ] Add explicit adapter identity fields for whatever Firefox 150 exposes:
  - vendor
  - architecture
  - device
  - description
  - backend or adapter type if exposed
- [ ] Add `webGpu.features` as an explicit string array.
- [ ] Add `webGpu.limits` as an explicit map of WebGPU limit names to numeric values.
- [ ] Add `webGpu.wgslLanguageFeatures` if Firefox exposes `navigator.gpu.wgslLanguageFeatures`.
- [ ] Add `webGpu.isFallbackAdapter` if Firefox exposes fallback adapter state.
- [ ] Add explicit values for synthetic mode; use seeds only for deterministic behavior that cannot be represented as explicit capabilities.

Patch TODO:

- [ ] Audit Firefox 150 WebGPU source paths and WebIDL.
- [ ] Confirm what Firefox 150 exposes from the host adapter versus normalized browser capabilities.
- [ ] Patch `navigator.gpu` exposure consistently in windows and workers only if profile policy requires a non-default result.
- [ ] Patch `GPU.requestAdapter()` to resolve or reject according to profile policy.
- [ ] Patch adapter info, features, limits, fallback state, and language features only for synthetic/coherence modes that need it.
- [ ] Ensure WebGPU state is per-context and uses the same storage model as navigator/WebGL/audio.
- [ ] Prevent raw host adapter info from leaking through logs, errors, crash annotations, or GPU-process IPC when the active policy is not native.
- [ ] Align WebGPU fallback behavior with Firefox standards behavior rather than throwing non-standard errors.

Test TODO:

- [ ] Add build-tester collection for `navigator.gpu`.
- [ ] Add tests for `requestAdapter()` success/failure.
- [ ] Add tests for adapter features and limits.
- [ ] Add worker tests for WebGPU availability.
- [ ] Add cross-signal tests against WebGL renderer/vendor, navigator platform, and OS.

## Phase 3: HTMLMediaElement.captureStream()

Risk: high. Firefox 150 exposes the standard `HTMLMediaElement.captureStream()` path behind `media.captureStream.enabled`. This creates another route into MediaStream, MediaRecorder, audio graph, WebRTC graph, timing, and track identity.

Temporary policy:

- [ ] Disable `media.captureStream.enabled` until behavior is audited.

Standards-compliant target:

- [ ] Support `captureStream()` when the media and audio profiles can make the resulting stream deterministic and coherent.
- [ ] Keep `mozCaptureStream()` compatibility behavior aligned with standard `captureStream()`.

Profile schema TODO:

- [ ] Decide whether to extend `mediaDevices` or add a new `mediaCapture` profile section.
- [ ] Add `mediaCapture.captureStreamEnabled`.
- [ ] Add deterministic seed or explicit policy for generated `MediaStreamTrack.id` values.
- [ ] Add explicit policy for audio/video track settings that derive from decoded media.
- [ ] Reuse `audioContext`, `audio`, `canvas`, and `mediaDevices` profile data where possible instead of adding duplicate knobs.

Patch TODO:

- [ ] Audit `HTMLMediaElement::CaptureStream` and related track creation code in Firefox 150.
- [ ] Patch track IDs, track labels if any, timing-sensitive output, and graph integration points.
- [ ] Ensure captured audio remains consistent with audio context spoofing.
- [ ] Ensure captured video remains consistent with canvas/rendering noise policy.
- [ ] Verify cross-origin media restrictions remain standards-compliant.

Test TODO:

- [ ] Add `HTMLMediaElement.prototype.captureStream` presence test.
- [ ] Add track ID determinism test.
- [ ] Add audio capture hash stability test.
- [ ] Add video/canvas capture stability test.
- [ ] Add MediaRecorder round-trip test if MediaRecorder is enabled.

## Phase 4: location.ancestorOrigins

Risk: medium-high. `Location.ancestorOrigins` exposes frame ancestry. It is not device entropy by itself, but it can make embedding and anti-bot environment checks more precise.

Temporary policy:

- [ ] Disable `dom.location.ancestorOrigins.enabled` until behavior is tested.

Standards-compliant target:

- [ ] If enabled, return standards-compliant origins for normal browsing.
- [ ] Avoid cross-context inconsistencies and non-standard empty values that can fingerprint Camoufox.

Profile/schema TODO:

- [ ] Decide whether this is a global privacy policy or profile-controlled behavior.
- [ ] If profile-controlled, add a `location` or `document.location` section with an `ancestorOriginsPolicy`.
- [ ] Do not add explicit fixed origin lists to the fingerprint unless a real use case requires synthetic embedding state.

Patch TODO:

- [ ] Audit Firefox 150 `Location` implementation and subject-principal checks.
- [ ] Confirm iframe, nested iframe, cross-origin iframe, and sandboxed iframe behavior.
- [ ] Patch only if pref-level disable is insufficient or creates detectable standards drift.

Test TODO:

- [ ] Add same-origin iframe test.
- [ ] Add cross-origin iframe test.
- [ ] Add sandboxed iframe test.
- [ ] Compare behavior against Firefox 150 release.

## Phase 5: Windows WinRT Geolocation Provider

Risk: high on Windows. Firefox 150 adds `geo.provider.use_winrt`. The existing geolocation patch masks final coordinates, but provider invocation can still trigger OS permission flows or reveal native provider behavior.

Profile schema TODO:

- [ ] Reuse existing `geolocation.latitude`, `geolocation.longitude`, and `geolocation.accuracy`.
- [ ] Do not add provider-specific profile fields unless Camoufox intentionally supports native geolocation providers.

Patch/config TODO:

- [x] Set `geo.provider.use_winrt=false` in `settings/camoufox.cfg`.
- [ ] Audit Windows geolocation provider construction and fallback paths.
- [ ] Confirm network geolocation and Wi-Fi scanning remain disabled.
- [ ] Confirm final `GeolocationPosition` values still come only from the profile.

Test TODO:

- [ ] Add Windows smoke test that geolocation returns profile coordinates.
- [ ] Add Windows smoke test that native location permission UI is not invoked.

## Phase 6: Safe Browsing Global Cache and Real-Time Checks

Risk: medium-high network/privacy. New real-time/global-cache paths can create external lookups or local cache state inconsistent with Camoufox network policy.

Profile schema TODO:

- [ ] Do not add fingerprint fields. This is a browser privacy/network policy, not persona identity.

Patch/config TODO:

- [ ] Disable new real-time Safe Browsing prefs explicitly.
- [ ] Disable new global cache prefs explicitly.
- [ ] Verify compile-time LibreWolf data-reporting patches still cover Firefox 150 code paths.
- [ ] Audit URL classifier, remote settings, and application reputation changes from 146 to 150.

Test TODO:

- [ ] Add network-block smoke test for Safe Browsing endpoints.
- [ ] Add pref assertion test in packaged profile.

## Phase 7: Local Network Access

Risk: medium. LNA is not classic fingerprint entropy, but it changes observable local-network probing, permission prompts, and localhost/local-network request behavior.

Profile schema TODO:

- [ ] Keep as global policy unless per-persona local-network behavior is required.
- [ ] If profile-controlled later, add `localNetworkAccess.policy` rather than host-derived local network details.

Patch/config TODO:

- [x] Pin target behavior for `network.lna.enabled` to Firefox 150 default `true`.
- [x] Pin target behavior for `network.lna.etp.enabled` to Firefox 150 default `true`.
- [x] Pin target behavior for `network.lna.block_insecure_contexts` to Firefox 150 default `true`.
- [x] Pin target behavior for localhost exemptions with `network.lna.local-network-to-localhost.skip-checks=true`.
- [ ] Ensure behavior is deterministic across OSes and proxy modes.

Test TODO:

- [ ] Add localhost fetch test.
- [ ] Add RFC1918 local-network fetch test in an isolated test network.
- [ ] Add cross-origin local-network request test.

## Phase 8: HDR, Color Spaces, and Display Capability Surfaces

Risk: medium. HDR and color-space features can expose display hardware or alter canvas/video output.

Policy:

- [x] Do not disable HDR/color-space behavior solely for entropy; prefer explicit profile values and native passthrough fallback.
- [x] Use profile values for display media-query surfaces when supplied.
- [ ] Decide separately whether HDR video rendering and color-input UI need profile controls.

Standards-compliant target:

- [x] Expose display media-query capabilities that are coherent with the selected screen, OS, GPU, and browser profile when explicit profile fields are supplied.
- [x] Preserve native/passthrough behavior when display profile fields are absent.

Profile schema TODO:

- [x] Extend `screen` with display media-query fields.
- [x] Add explicit `colorGamut` value.
- [x] Add explicit `dynamicRange` value.
- [x] Add explicit `videoDynamicRange` value.
- [ ] Add explicit `forcedColors`, `prefersContrast`, and related media-query values if currently host-derived.
- [ ] Avoid seed-only display capabilities; these should be explicit coherent values.

Patch/config TODO:

- [x] Audit CSS media query code paths for color and dynamic range.
- [x] Patch `color-gamut`, CSS `color` depth, `dynamic-range`, and `video-dynamic-range` to honor profile values when present.
- [x] Regenerate OpenAPI Python/C++ models and update the Python fingerprint compiler to carry display fields from presets/mappings.
- [ ] Audit HTML color input behavior when `dom.forms.colorspace.enabled` is true.
- [ ] Audit canvas/video color management paths for host display influence.

Test TODO:

- [x] Validate `example/fingerprint.json` with display fields.
- [x] Run a compiler serialization smoke test for preset display fields.
- [ ] Add `matchMedia("(dynamic-range: high)")` test.
- [ ] Add `matchMedia("(color-gamut: p3)")` and `rec2020` tests.
- [ ] Add canvas color-output stability test.
- [ ] Add video color-output stability test where practical.

## Phase 9: Digital Credentials and WebAuthn Changes

Risk: medium. Credential APIs can expose platform authenticator availability, transports, user-verification support, and enterprise/security state.

Temporary policy:

- [ ] Keep `dom.security.credentialmanagement.digital.enabled=false`.
- [ ] Review `security.webauthn.allow_with_certificate_override`.

Profile schema TODO:

- [ ] If enabling later, add a `credentials` or `webAuthn` profile section.
- [ ] Model platform authenticator availability explicitly.
- [ ] Model transports explicitly.
- [ ] Model user-verification and resident-key support explicitly.
- [ ] Model attestation policy explicitly.

Patch TODO:

- [ ] Audit Firefox 150 credential-management and WebAuthn changes.
- [ ] Ensure no platform authenticator state leaks when disabled.
- [ ] Ensure certificate override behavior does not alter WebAuthn behavior unexpectedly.

Test TODO:

- [ ] Add public-key credential availability test.
- [ ] Add digital credential API absence test while disabled.

## Phase 10: Reporting API and CSP Reporting

Risk: low-medium by default. `dom.reporting.enabled` appears disabled by default, but if enabled it can store reports, deliver network requests, and expose browser behavior.

Temporary policy:

- [ ] Keep Reporting API disabled.

Standards-compliant target:

- [ ] If enabled, use per-context ephemeral report storage and deterministic delivery behavior.

Profile schema TODO:

- [ ] Keep as global policy unless sites require enabled Reporting API.
- [ ] If enabled later, add `reporting.enabled` and report delivery policy fields.

Patch/config TODO:

- [ ] Set `dom.reporting.enabled=false`.
- [ ] Set `dom.reporting.header.enabled=false`.
- [ ] Review `security.csp.reporting.enabled` if present in Firefox 150.
- [ ] Audit report persistence and network delivery paths.

Test TODO:

- [ ] Add `ReportingObserver` absence/presence test.
- [ ] Add CSP report endpoint network-block test.

## Phase 11: Navigator ModelContext and Local AI Surfaces

Risk: low today if disabled, high if enabled later. Local model availability is high entropy and can identify device capability or installed components.

Temporary policy:

- [ ] Set `dom.modelcontext.enabled=false`.

Profile schema TODO:

- [ ] If enabling later, add `modelContext` profile section.
- [ ] Model availability explicitly.
- [ ] Model supported input/output capabilities explicitly.
- [ ] Never use host installed model inventory implicitly.

Patch/test TODO:

- [ ] Add navigator `modelContext` absence test while disabled.
- [ ] Audit future Firefox releases for additional local AI APIs.

## Phase 12: WebGL Revalidation for Firefox 150

Risk: medium. Existing WebGL spoofing is broad, but Firefox 150 adds or reorganizes WebGL prefs and code paths.

Profile schema TODO:

- [ ] Reuse existing `webGl` and `webGl2` profile sections if all Firefox 150 parameters still fit.
- [ ] Add schema fields only for newly exposed values that cannot fit `parameters`, `shaderPrecisionFormats`, `contextAttributes`, or extension lists.

Patch TODO:

- [ ] Audit `webgl.allow-in-content`.
- [ ] Audit `webgl.allow-in-parent`.
- [ ] Audit any changed `getParameter`, extension, shader precision, and context creation paths.
- [ ] Confirm WebGL2 handling still mirrors WebGL profile policy.
- [ ] Confirm GPU/WebGL cross-signal consistency after WebGPU work.

Test TODO:

- [ ] Run existing WebGL collector against Firefox 150.
- [ ] Add tests for any new WebGL parameters or changed defaults.
- [ ] Add cross-signal tests for WebGL vs WebGPU.

## Phase 13: Permissions and Storage Behavior

Risk: low-medium. New permission expiry behavior can change persistent state and automation behavior.

Profile schema TODO:

- [ ] Keep as global browser policy unless per-persona permission persistence becomes required.

Patch/config TODO:

- [ ] Review `permissions.expireUnused.enabled`.
- [ ] Review `permissions.expireUnusedThresholdSec`.
- [ ] Review `permissions.expireUnusedTypes`.
- [ ] Confirm permission state remains per-context and automation-friendly.

Test TODO:

- [ ] Add permissions persistence regression test.
- [ ] Add geolocation/camera/microphone permission behavior test.

## Phase 14: Removed or Reorganized Firefox 146 Prefs

Risk: low, but dead prefs can create false confidence.

TODO:

- [ ] Review removed `network.predictor.*` prefs.
- [ ] Review removed or reorganized `media.mediasource.*` prefs.
- [ ] Review removed async clipboard prefs.
- [ ] Review removed `webgl.prefer-16bpp`.
- [ ] Remove or comment dead prefs only after verifying Firefox 150 ignores them safely.
- [ ] Document any pref removals in the migration PR.

## Phase 15: Test Harness Expansion

TODO:

- [ ] Extend `__tests__/build-tester/src/lib/checks/collectors.ts` for new browser surfaces.
- [ ] Add WebGPU collector and consistency checks.
- [ ] Add `captureStream()` collector and stability checks.
- [ ] Add `location.ancestorOrigins` iframe collector.
- [ ] Add HDR/color media-query collector.
- [ ] Add Reporting API absence/presence collector.
- [ ] Add Digital Credentials/WebAuthn absence/presence collector.
- [ ] Add ModelContext absence collector.
- [ ] Add pref assertions for new hard-disable prefs where tests can read packaged config.
- [ ] Add per-context tests for all new profile fields.
- [ ] Add worker/service-worker tests for every API that can appear outside Window.

## Phase 16: BrowserForge and Python Fingerprint Pipeline

TODO:

- [ ] Confirm BrowserForge supports Firefox 150 fingerprints.
- [ ] Update tests currently pinned to `ff_version="146"`.
- [ ] Ensure generated UA, `navigator.appVersion`, `oscpu`, platform, language, Accept-Language, WebGL, screen, and media values remain coherent for Firefox 150.
- [ ] Add generated defaults for any new schema fields.
- [ ] Ensure random seeds are generated only for fields designed to be seed-derived:
  - canvas noise
  - audio noise
  - font spacing
  - media capture track IDs if implemented as seed-derived
  - WebGPU nondeterministic behavior only when synthetic/coherence mode cannot use explicit standard values
- [ ] Ensure explicit values are used for fields that should be coherent platform facts:
  - WebGPU policy, adapter identity, limits, and features when not using native passthrough
  - display color/dynamic range
  - WebAuthn capability policy
  - geolocation coordinates
  - locale/timezone

## Phase 17: Build and Release Acceptance

TODO:

- [ ] `CAMOUFOX_FIREFOX_VERSION=150.0.1 make fetch`
- [ ] `CAMOUFOX_FIREFOX_VERSION=150.0.1 make setup`
- [x] `CAMOUFOX_FIREFOX_VERSION=150.0.1 make dir`
- [x] Full build on primary development platform.
- [x] Package smoke test via `CAMOUFOX_FIREFOX_VERSION=150.0.1 ./mach run --version`.
- [ ] `make lint`
- [ ] Python fingerprint pipeline tests.
- [ ] Build tester suite.
- [ ] Playwright suite.
- [ ] Service tester suite.
- [ ] Manual smoke test for browser launch, page navigation, context creation, proxy configuration, and per-context fingerprint isolation.
- [ ] Update `upstream.sh` only once the patch stack and blocking feature policies are green.

## Open Decisions

- [ ] Should Firefox 150 WebGPU use native/passthrough as the default policy, with synthetic/coherence mode added only when BrowserForge chooses non-native GPU facts?
- [ ] Should `captureStream()` ship disabled first, or do we need standards-compliant support in the first Firefox 150 binary?
- [ ] Should `location.ancestorOrigins` be disabled for privacy uniformity or enabled to match Firefox 150 standards behavior?
- [ ] Should LNA follow Firefox defaults for standards compliance or be pinned to stricter deterministic network policy?
- [ ] Should display color/HDR be modeled under `screen` or a new `display` profile section?
