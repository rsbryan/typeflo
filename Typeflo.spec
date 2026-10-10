from pathlib import Path
import tomllib
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
build_number = str(sum(int(part) * factor for part, factor in zip(version.split("."), (10000, 100, 1))))
datas = [(str(root / "src/dictate/resources"), "dictate/resources")]
hiddenimports = []
datas += collect_data_files("mlx", excludes=["include/**", "share/**", "lib/cmake/**"])
for package in ("mlx_lm", "parakeet_mlx", "librosa", "transformers", "tokenizers"):
    datas += collect_data_files(package)
for package in ("mlx", "mlx_lm", "parakeet_mlx", "librosa", "transformers.models.auto", "transformers.models.qwen2"):
    hiddenimports += collect_submodules(package)
hiddenimports += ["mlx.core", "mlx.nn", "mlx_lm.generate", "mlx_lm.sample_utils", "mlx_lm.tokenizer_utils",
                  "transformers.tokenization_utils_tokenizers", "transformers.tokenization_utils_sentencepiece",
                  "sounddevice", "soundfile",
                  "WebKit", "AVFoundation", "CoreMedia", "Quartz", "ApplicationServices", "AppKit"]
for package in ("mlx", "mlx-lm", "parakeet-mlx", "transformers", "tokenizers", "huggingface-hub", "numpy",
                "tqdm", "regex", "safetensors", "packaging", "pyyaml", "filelock", "requests"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass
a = Analysis([str(root / "scripts/app-entry.py")], pathex=[str(root / "src")],
             binaries=[], datas=datas, hiddenimports=hiddenimports,
             excludes=["torch", "tensorflow", "jax", "matplotlib", "IPython", "pytest", "tkinter"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Typeflo", debug=False,
          strip=False, upx=False, console=False, target_arch="arm64")
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Typeflo")
app = BUNDLE(collection, name="Typeflo.app", icon=str(root / "src/dictate/resources/Typeflo.icns"),
             bundle_identifier="local.typeflo.app", info_plist={
                 "CFBundleName": "Typeflo", "CFBundleDisplayName": "Typeflo",
                 "CFBundleShortVersionString": version, "CFBundleVersion": build_number,
                 "LSUIElement": False, "LSMultipleInstancesProhibited": True,
                 "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "14.0",
                 "NSMicrophoneUsageDescription": "Typeflo records your voice while you dictate. Audio is processed on this Mac and never uploaded.",
                 "NSAppleEventsUsageDescription": "Typeflo uses macOS integration to insert your dictation into the app you are using.",
                 "NSPrincipalClass": "NSApplication",
             })
