import threading
import uuid
import webbrowser

from flask import Flask, abort, jsonify, render_template, request, send_file
from pytubefix import YouTube
from pytubefix.exceptions import RegexMatchError

from yout import baixar, resolucoes_disponiveis

app = Flask(__name__)

tarefas: dict[str, dict] = {}
trava = threading.Lock()


def _atualizar(id_tarefa: str, **campos) -> None:
    with trava:
        tarefas[id_tarefa].update(campos)


def _executar(id_tarefa: str, opcoes: dict) -> None:
    def reportar(msg, pct):
        _atualizar(id_tarefa, mensagem=msg, progresso=pct)

    try:
        arquivo = baixar(reportar=reportar, **opcoes)
        _atualizar(id_tarefa, status="concluido", mensagem="Download concluído!",
                   progresso=100, arquivo=str(arquivo), nome=arquivo.name)
    except Exception as e:
        _atualizar(id_tarefa, status="erro", mensagem=str(e), progresso=None)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/info")
def info():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify(erro="Informe uma URL."), 400
    try:
        yt = YouTube(url)
        return jsonify(
            titulo=yt.title,
            autor=yt.author,
            duracao=yt.length,
            miniatura=yt.thumbnail_url,
            resolucoes=resolucoes_disponiveis(yt),
        )
    except RegexMatchError:
        return jsonify(erro="URL inválida. Cole o link completo de um vídeo do YouTube."), 400
    except Exception as e:
        return jsonify(erro=f"Não foi possível obter o vídeo: {e}"), 400


@app.post("/api/baixar")
def iniciar_download():
    dados = request.json or {}
    url = dados.get("url", "").strip()
    if not url:
        return jsonify(erro="Informe uma URL."), 400

    opcoes = {
        "url": url,
        "qualidade": str(dados.get("qualidade", "max")),
        "apenas_audio": dados.get("tipo") == "audio",
        "formato_audio": "m4a" if dados.get("formato_audio") == "m4a" else "mp3",
        "h264": bool(dados.get("h264")),
    }
    id_tarefa = uuid.uuid4().hex
    with trava:
        tarefas[id_tarefa] = {"status": "baixando", "mensagem": "Iniciando...", "progresso": None}
    threading.Thread(target=_executar, args=(id_tarefa, opcoes), daemon=True).start()
    return jsonify(id=id_tarefa)


@app.get("/api/status/<id_tarefa>")
def status(id_tarefa: str):
    with trava:
        tarefa = tarefas.get(id_tarefa)
        if tarefa is None:
            abort(404)
        return jsonify({k: v for k, v in tarefa.items() if k != "arquivo"})


@app.get("/api/arquivo/<id_tarefa>")
def arquivo(id_tarefa: str):
    with trava:
        tarefa = tarefas.get(id_tarefa)
    if not tarefa or tarefa.get("status") != "concluido":
        abort(404)
    return send_file(tarefa["arquivo"], as_attachment=True, download_name=tarefa["nome"])


if __name__ == "__main__":
    endereco = "http://127.0.0.1:5000"
    print(f"Abra {endereco} no navegador (Ctrl+C para encerrar).")
    threading.Timer(1.0, lambda: webbrowser.open(endereco)).start()
    app.run(host="127.0.0.1", port=5000, threaded=True)
