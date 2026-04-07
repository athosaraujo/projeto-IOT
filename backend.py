from contextlib import asynccontextmanager
from threading import Lock
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import paho.mqtt.client as mqtt


# CONFIGURAÇÕES
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

TOPIC_STATUS = "esp32/luz/status"
TOPIC_LDR = "esp32/luz/ldr"
TOPIC_LED = "esp32/luz/led"
TOPIC_MODE = "esp32/luz/cmd/modo"
TOPIC_LED_MANUAL = "esp32/luz/cmd/led"


# ESTADO GLOBAL
state_lock = Lock()

estado = {
    "mqtt_conectado": False,
    "status_esp32": "desconhecido",
    "luminosidade": 0,
    "duty": 0,
    "ultimo_update": None,
    "ultima_origem": None,
    "erro_mqtt": ""
}

mqtt_client = None


# MODELOS
class ModoPayload(BaseModel):
    modo: str


class BrilhoPayload(BaseModel):
    valor: int


# AUXILIARES
def atualizar_estado(**kwargs):
    with state_lock:
        for k, v in kwargs.items():
            estado[k] = v


def obter_estado():
    with state_lock:
        copia = dict(estado)

    if copia["ultimo_update"] is not None:
        copia["idade_dados_segundos"] = round(time.time() - copia["ultimo_update"], 2)
    else:
        copia["idade_dados_segundos"] = None

    return copia


def criar_cliente_mqtt():
    global mqtt_client

    try:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="backend-iot-led",
            protocol=mqtt.MQTTv311
        )
    except AttributeError:
        client = mqtt.Client(
            client_id="backend-iot-led",
            protocol=mqtt.MQTTv311
        )

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            atualizar_estado(
                mqtt_conectado=True,
                erro_mqtt=""
            )
            client.subscribe(TOPIC_STATUS)
            client.subscribe(TOPIC_LDR)
            client.subscribe(TOPIC_LED)
            print(f"✅ Backend conectado ao broker MQTT em {MQTT_BROKER}:{MQTT_PORT}")
        else:
            atualizar_estado(
                mqtt_conectado=False,
                erro_mqtt=f"Falha no connect rc={rc}"
            )
            print(f"❌ Falha ao conectar no MQTT. rc={rc}")

    def on_disconnect(client, userdata, rc):
        atualizar_estado(
            mqtt_conectado=False,
            erro_mqtt=f"Desconectado rc={rc}"
        )
        print(f"⚠️ MQTT desconectado. rc={rc}")

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode().strip()

            if msg.topic == TOPIC_STATUS:
                atualizar_estado(
                    status_esp32=payload,
                    ultimo_update=time.time(),
                    ultima_origem=TOPIC_STATUS
                )

            elif msg.topic == TOPIC_LDR:
                atualizar_estado(
                    luminosidade=int(payload),
                    ultimo_update=time.time(),
                    ultima_origem=TOPIC_LDR
                )

            elif msg.topic == TOPIC_LED:
                atualizar_estado(
                    duty=int(payload),
                    ultimo_update=time.time(),
                    ultima_origem=TOPIC_LED
                )

        except Exception as e:
            print(f"Erro ao processar mensagem MQTT: {e}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()

    mqtt_client = client
    return client


def publicar(topic: str, payload: str):
    global mqtt_client

    if mqtt_client is None:
        raise RuntimeError("Cliente MQTT ainda não foi inicializado.")

    snap = obter_estado()
    if not snap["mqtt_conectado"]:
        raise RuntimeError(f"MQTT desconectado: {snap['erro_mqtt']}")

    info = mqtt_client.publish(topic, str(payload))
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"Falha ao publicar. rc={info.rc}")


# LIFESPAN FASTAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client

    try:
        criar_cliente_mqtt()
    except Exception as e:
        atualizar_estado(
            mqtt_conectado=False,
            erro_mqtt=str(e)
        )
        print(f"❌ Erro ao iniciar MQTT no backend: {e}")

    yield

    if mqtt_client is not None:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception:
            pass


app = FastAPI(title="Backend IoT LED", lifespan=lifespan)


# ROTAS
@app.get("/health")
def health():
    return {
        "ok": True,
        "servico": "backend-iot-led",
        "mqtt": obter_estado()["mqtt_conectado"]
    }


@app.get("/dados")
def dados():
    return obter_estado()


@app.post("/modo")
def definir_modo(payload: ModoPayload):
    modo = payload.modo.strip().lower()

    if modo not in {"auto", "manual"}:
        raise HTTPException(status_code=400, detail="Modo deve ser 'auto' ou 'manual'.")

    try:
        publicar(TOPIC_MODE, modo)
        return {
            "ok": True,
            "mensagem": f"Modo enviado: {modo}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/brilho")
def definir_brilho(payload: BrilhoPayload):
    valor = int(payload.valor)

    if valor < 0 or valor > 255:
        raise HTTPException(status_code=400, detail="O brilho deve estar entre 0 e 255.")

    try:
        publicar(TOPIC_LED_MANUAL, str(valor))
        return {
            "ok": True,
            "mensagem": f"Brilho manual enviado: {valor}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))