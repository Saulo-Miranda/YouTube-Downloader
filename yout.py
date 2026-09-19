import argparse
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

from pytubefix import YouTube

PASTA_DESTINO = Path(__file__).parent / "downloads"

# reportar(mensagem, porcentagem) — porcentagem é None quando a etapa não tem progresso mensurável
Reporter = Callable[[str, Optional[float]], None]


def _altura(stream) -> int:
    try:
        return int((stream.resolution or "0").rstrip("p"))
    except ValueError:
        return 0


def _escolher_video(yt: YouTube, max_altura: Optional[int], h264: bool):
    candidatos = [
        s for s in yt.streams.filter(adaptive=True, only_video=True, file_extension="mp4")
        if (max_altura is None or _altura(s) <= max_altura)
        and (not h264 or (s.video_codec or "").startswith("avc1"))
    ]
    candidatos.sort(key=lambda s: (_altura(s), s.fps or 0, s.bitrate or 0), reverse=True)
    return candidatos[0] if candidatos else None


def _ffmpeg(ffmpeg: str, *args: str) -> None:
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args], check=True)


def resolucoes_disponiveis(yt: YouTube) -> list[int]:
    alturas = {_altura(s) for s in yt.streams.filter(adaptive=True, only_video=True, file_extension="mp4")}
    return sorted((a for a in alturas if a), reverse=True)


def baixar(
    url: str,
    qualidade: str = "max",
    apenas_audio: bool = False,
    formato_audio: str = "mp3",
    h264: bool = False,
    pasta: Path = PASTA_DESTINO,
    reportar: Reporter = lambda msg, pct: None,
) -> Path:
    """Baixa um vídeo (ou só o áudio) do YouTube e retorna o caminho do arquivo final.

    qualidade: "max" ou a altura máxima em pixels (ex.: "1080").
    h264: restringe o vídeo ao codec H.264, que abre em qualquer player.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    etapa = {"nome": ""}

    def on_progress(stream, _chunk, bytes_restantes):
        total = stream.filesize or 1
        reportar(etapa["nome"], (total - bytes_restantes) / total * 100)

    reportar("Obtendo informações do vídeo...", None)
    yt = YouTube(url, on_progress_callback=on_progress)
    ffmpeg = shutil.which("ffmpeg")
    prefixo = f"tmp_{uuid.uuid4().hex[:8]}_"

    if apenas_audio:
        audio = yt.streams.get_audio_only()
        if audio is None:
            raise RuntimeError("Nenhum stream de áudio disponível.")
        etapa["nome"] = "Baixando áudio..."
        arq = Path(audio.download(output_path=str(pasta), filename_prefix=prefixo))
        nome_final = Path(audio.default_filename).stem
        if formato_audio == "mp3" and ffmpeg:
            reportar("Convertendo para MP3...", None)
            saida = pasta / f"{nome_final}.mp3"
            _ffmpeg(ffmpeg, "-i", str(arq), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(saida))
            arq.unlink(missing_ok=True)
        else:
            saida = pasta / f"{nome_final}.m4a"
            arq.replace(saida)
        return saida

    max_altura = None if qualidade == "max" else int(qualidade)

    if not ffmpeg:
        # Sem ffmpeg não dá para juntar áudio e vídeo: usa stream progressivo (máx. ~360p)
        stream = (
            yt.streams.filter(progressive=True, file_extension="mp4")
            .order_by("resolution").desc().first()
        )
        if stream is None:
            raise RuntimeError("Nenhum stream MP4 progressivo disponível.")
        etapa["nome"] = f"Baixando {stream.resolution} (ffmpeg não encontrado)..."
        return Path(stream.download(output_path=str(pasta)))

    video = _escolher_video(yt, max_altura, h264)
    audio = yt.streams.get_audio_only()
    if video is None:
        raise RuntimeError("Nenhum stream de vídeo atende à qualidade/codec escolhidos.")
    if audio is None:
        raise RuntimeError("Nenhum stream de áudio disponível.")

    etapa["nome"] = f"Baixando vídeo {video.resolution}..."
    arq_video = Path(video.download(output_path=str(pasta), filename_prefix=prefixo + "v_"))
    etapa["nome"] = "Baixando áudio..."
    arq_audio = Path(audio.download(output_path=str(pasta), filename_prefix=prefixo + "a_"))

    reportar("Juntando áudio e vídeo...", None)
    saida = pasta / f"{Path(video.default_filename).stem} ({video.resolution}).mp4"
    try:
        _ffmpeg(ffmpeg, "-i", str(arq_video), "-i", str(arq_audio), "-c", "copy", str(saida))
    finally:
        arq_video.unlink(missing_ok=True)
        arq_audio.unlink(missing_ok=True)
    return saida


def main() -> int:
    parser = argparse.ArgumentParser(description="Download de vídeos do YouTube")
    parser.add_argument("url", nargs="?", help="URL do vídeo")
    parser.add_argument("-q", "--qualidade", default="max", help='"max" ou altura máxima, ex.: 1080')
    parser.add_argument("-a", "--audio", choices=["mp3", "m4a"], help="baixar somente o áudio")
    parser.add_argument("--h264", action="store_true", help="vídeo em H.264 (compatível com qualquer player)")
    args = parser.parse_args()

    url = args.url or input("URL do vídeo: ").strip()
    if not url:
        print("Nenhuma URL informada.")
        return 1

    def reportar(msg, pct):
        linha = f"{msg} {pct:5.1f}%" if pct is not None else msg
        print(f"\r{linha:<70}", end="" if pct is not None and pct < 100 else "\n", flush=True)

    try:
        arquivo = baixar(url, args.qualidade, bool(args.audio), args.audio or "mp3", args.h264,
                         reportar=reportar)
    except Exception as e:
        print(f"\nErro ao baixar: {e}")
        return 1

    print(f"Concluído: {arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
