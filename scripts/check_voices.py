"""Проверка установленных голосов Windows SAPI и синтеза речи.

Запуск::

    python -m scripts.check_voices
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
Write-Output "--- VOICES ---"
foreach ($v in $s.GetInstalledVoices()) {
    Write-Output ($v.VoiceInfo.Name + " | culture=" + $v.VoiceInfo.Culture.Name + " | enabled=" + $v.Enabled)
}
Write-Output "--- SYNTH TEST ---"
$out = Join-Path $env:TEMP "sapi_probe.wav"
if (Test-Path $out) { Remove-Item $out -Force }
$ru = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "ru*" -and $_.Enabled } | Select-Object -First 1
if ($ru) { $s.SelectVoice($ru.VoiceInfo.Name); Write-Output ("selected: " + $ru.VoiceInfo.Name) }
else { Write-Output "no ru voice; using default" }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($out, $fmt)
$s.Speak("Потратил тысяча двести пятьдесят рублей на продукты")
$s.Dispose()
if (Test-Path $out) { Write-Output ("WAV OK: " + (Get-Item $out).Length + " bytes -> " + $out) }
else { Write-Output "WAV NOT CREATED" }
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "probe.ps1"
        script_path.write_text(SCRIPT, encoding="utf-8-sig")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    report = (result.stdout or "") + "\n--- STDERR ---\n" + (result.stderr or "")
    (PROJECT_ROOT / ".report" / "voices.txt").write_text(report, encoding="utf-8")
    print(report[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
