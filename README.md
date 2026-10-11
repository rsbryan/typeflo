# Typeflo

On-device push-to-talk dictation for Apple Silicon Macs. Hold a key, speak, release, and cleaned-up text lands at your cursor in whatever app is focused. Speech recognition runs on [Parakeet MLX](https://github.com/senstella/parakeet-mlx) and transcript cleanup on a 4-bit Qwen model through [mlx-lm](https://github.com/ml-explore/mlx-lm). Nothing leaves your Mac.

## Requirements

- Apple Silicon Mac on macOS 14 or newer
- Xcode Command Line Tools (`xcode-select --install`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- About 4 GB of disk for the default models, downloaded once from Hugging Face

## Install

```sh
git clone https://github.com/rsbryan/typeflo.git
cd typeflo
bash scripts/build-app.sh
```

The script bundles the app, signs it, installs it to `/Applications/Typeflo.app`, and launches it. On first launch:

1. Click **Microphone** and allow the prompt.
2. Click **Accessibility**, then switch Typeflo on in the System Settings list that opens. This covers the hotkey and pasting. Input Monitoring is not needed.
3. Open **Models** and download the default pair.
4. If you keep the default **Fn** hotkey, set **System Settings > Keyboard > Press Globe key to: Do Nothing** so the emoji picker stays closed.

If Accessibility shows as on but Typeflo still reports it missing, remove Typeflo from the Accessibility list with the minus button and click the button again.

## Use

- **Push to talk**: hold Fn, speak, release.
- **Hands-free**: Fn + Space to start, again to stop.
- **Cancel**: Escape while recording.
- Closing the window keeps Typeflo running in the menu bar. Cmd-Q quits.

Dictated text is fitted to where it lands: a word inserted mid-sentence stays lowercase with no trailing period, and spaces are added only where needed. Cleanup removes fillers and fixes punctuation but keeps your exact words; if the model rewords anything, Typeflo pastes the raw transcript instead.

The window has history, insights with timings, a personal dictionary, snippets, writing styles, model switching, and settings. Settings live in `~/.config/typeflo/config.toml`; history and logs are in `~/Library/Application Support/Typeflo`.

## Update

```sh
cd typeflo
git pull
bash scripts/build-app.sh
```

The build script signs with the first Apple Development certificate in your keychain when one exists. Without one it uses an ad-hoc signature, and macOS forgets the Accessibility grant on every rebuild, so step 2 above repeats after each update.

## Run from source

```sh
uv sync
uv run typeflo --download-models
uv run typeflo
```

Grant Microphone and Accessibility to the process macOS names in the prompt.

## Development

```sh
uv run python -m unittest discover -s tests -v
bash scripts/bench.sh
```

Source is under `src/dictate`. Tests cover config, hotkey parsing, cleanup, clipboard restore, silence trimming, snippets, and history. Microphone capture and paste delivery need a live macOS check.

## License

MIT
