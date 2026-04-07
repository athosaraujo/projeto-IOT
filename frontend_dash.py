from collections import deque
from datetime import datetime

import requests
import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, no_update
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# CONFIGURAÇÕES
BACKEND_URL = "http://127.0.0.1:8000"
MAX_PONTOS = 200

hist_tempo = deque(maxlen=MAX_PONTOS)
hist_duty_pct = deque(maxlen=MAX_PONTOS)
hist_ldr = deque(maxlen=MAX_PONTOS)

app = Dash(__name__)
server = app.server


# FUNÇÕES
def calcular_duty_pct(duty: int) -> float:
    return round(max(0.0, min(100.0, (duty / 255.0) * 100.0)), 1)


def buscar_dados():
    resp = requests.get(f"{BACKEND_URL}/dados", timeout=3)
    resp.raise_for_status()
    return resp.json()


def enviar_modo(modo: str):
    resp = requests.post(
        f"{BACKEND_URL}/modo",
        json={"modo": modo},
        timeout=3
    )
    resp.raise_for_status()
    return resp.json()


def enviar_brilho(valor: int):
    resp = requests.post(
        f"{BACKEND_URL}/brilho",
        json={"valor": int(valor)},
        timeout=3
    )
    resp.raise_for_status()
    return resp.json()


def montar_figura():
    df = pd.DataFrame({
        "tempo": list(hist_tempo),
        "duty_pct": list(hist_duty_pct),
        "ldr": list(hist_ldr),
    })
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=df["tempo"], y=df["duty_pct"], mode="lines", name="Duty Cycle (%)"),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(x=df["tempo"], y=df["ldr"], mode="lines", name="LDR (ADC)"),
        secondary_y=True
    )
    fig.update_layout(
        title="Evolução em tempo real",
        height=500,
        margin=dict(l=30, r=30, t=50, b=30),
        legend=dict(orientation="h", y=1.08, x=0)
    )
    fig.update_yaxes(title_text="Duty Cycle (%)", range=[0, 100], secondary_y=False)
    fig.update_yaxes(title_text="LDR (ADC)", range=[0, 4095], secondary_y=True)
    fig.update_xaxes(title_text="Horário")
    return fig

# LAYOUT
app.layout = html.Div(
    style={"padding": "20px", "fontFamily": "Arial"},
    children=[
        html.H1("Dashboard IoT - Iluminação controlada por LDR"),
        html.P("ESP32 + Mosquitto + Backend Python + Front Dash"),

        dcc.Interval(id="intervalo", interval=1000, n_intervals=0),

        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 2fr", "gap": "20px"},
            children=[
                html.Div(
                    style={"border": "1px solid #ddd", "borderRadius": "12px", "padding": "16px"},
                    children=[
                        html.H3("Controles"),

                        html.Label("Modo"),
                        dcc.Dropdown(
                            id="modo-dropdown",
                            options=[
                                {"label": "Automático", "value": "auto"},
                                {"label": "Manual", "value": "manual"},
                            ],
                            value="auto",
                            clearable=False
                        ),
                        html.Br(),
                        html.Button("Enviar modo", id="btn-modo", n_clicks=0),

                        html.Br(),
                        html.Br(),

                        html.Label("Brilho manual"),
                        dcc.Slider(
                            id="brilho-slider",
                            min=0,
                            max=255,
                            step=1,
                            value=0,
                            marks={0: "0", 128: "128", 255: "255"}
                        ),
                        html.Br(),
                        html.Button("Enviar brilho", id="btn-brilho", n_clicks=0),

                        html.Hr(),

                        html.Div(id="status-backend"),
                        html.Div(id="status-esp32"),
                        html.Div(id="idade-dado"),
                        html.Div(id="mensagem-acao", style={"marginTop": "12px", "fontWeight": "bold"}),
                    ]
                ),

                html.Div(
                    style={"border": "1px solid #ddd", "borderRadius": "12px", "padding": "16px"},
                    children=[
                        html.H3("Métricas"),
                        html.Div(
                            style={"display": "grid", "gridTemplateColumns": "repeat(2, 1fr)", "gap": "12px"},
                            children=[
                                html.Div(id="card-ldr"),
                                html.Div(id="card-duty"),
                            ]
                        ),
                        html.Br(),
                        dcc.Graph(id="grafico-live")
                    ]
                ),
            ]
        )
    ]
)


# CALLBACK DE ATUALIZAÇÃO
@app.callback(
    Output("grafico-live", "figure"),
    Output("card-ldr", "children"),
    Output("card-duty", "children"),
    Output("status-backend", "children"),
    Output("status-esp32", "children"),
    Output("idade-dado", "children"),
    Input("intervalo", "n_intervals"),
)
def atualizar_dashboard(n):
    try:
        dados = buscar_dados()
        ldr = int(dados.get("luminosidade", 0))
        duty = int(dados.get("duty", 0))
        duty_pct = calcular_duty_pct(duty)
        hist_tempo.append(datetime.now())
        hist_duty_pct.append(duty_pct)
        hist_ldr.append(ldr)
        fig = montar_figura()
        card_ldr = html.Div([
            html.H4("LDR (ADC)"),
            html.H2(str(ldr))
        ], style={"border": "1px solid #ddd", "borderRadius": "10px", "padding": "12px"})
        card_duty = html.Div([
            html.H4("Duty Cycle"),
            html.H2(f"{duty_pct}%")
        ], style={"border": "1px solid #ddd", "borderRadius": "10px", "padding": "12px"})
        status_backend = f"Backend MQTT: {'conectado' if dados.get('mqtt_conectado') else 'desconectado'}"
        status_esp32 = f"Status ESP32: {dados.get('status_esp32', 'desconhecido')}"
        idade = f"Idade do dado: {dados.get('idade_dados_segundos')} s"
        return fig, card_ldr, card_duty, status_backend, status_esp32, idade
    except Exception as e:
        fig = go.Figure()
        fig.update_layout(title=f"Erro ao atualizar: {e}")
        return (
            fig,
            "Erro",
            "Erro",
            "Backend MQTT: erro",
            "Status ESP32: erro",
            f"Detalhe: {e}",
        )


# CALLBACK ENVIAR MODO
@app.callback(
    Output("mensagem-acao", "children", allow_duplicate=True),
    Input("btn-modo", "n_clicks"),
    State("modo-dropdown", "value"),
    prevent_initial_call=True
)
def acao_modo(n_clicks, modo):
    try:
        enviar_modo(modo)
        return f"Modo enviado com sucesso: {modo}"
    except Exception as e:
        return f"Erro ao enviar modo: {e}"


# CALLBACK ENVIAR BRILHO
@app.callback(
    Output("mensagem-acao", "children", allow_duplicate=True),
    Input("btn-brilho", "n_clicks"),
    State("brilho-slider", "value"),
    prevent_initial_call=True
)
def acao_brilho(n_clicks, brilho):
    try:
        enviar_brilho(int(brilho))
        return f"Brilho enviado com sucesso: {brilho}"
    except Exception as e:
        return f"Erro ao enviar brilho: {e}"


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)