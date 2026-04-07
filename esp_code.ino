#include <WiFi.h>
#include <PubSubClient.h>

// CONEXÃO WI-FI
const char* WIFI_SSID     = "XXXXX";
const char* WIFI_PASSWORD = "xxxxxxxx";

// CONFIGURAÇÕES DO MQTT
const char* MQTT_BROKER = "192.168.1.100"; // Seu IP aqui
const int   MQTT_PORT     = 1883;

const char* TOPIC_STATUS       = "esp32/luz/status";
const char* TOPIC_LDR          = "esp32/luz/ldr";
const char* TOPIC_LED          = "esp32/luz/led";
const char* TOPIC_MODE         = "esp32/luz/cmd/modo";
const char* TOPIC_LED_MANUAL   = "esp32/luz/cmd/led";

// PINOS
const int PIN_LDR = 34;
const int PIN_LED = 4;   

// PWM
const int PWM_FREQ = 5000;
const int PWM_RES = 8;

// CONTROLE
bool modoAutomatico = true;
int brilhoManual = 0;
float brilhoFiltrado = 0.0;

WiFiClient espClient;
PubSubClient client(espClient);

// TIMERS
unsigned long ultimoControle = 0;
unsigned long ultimaPublicacao = 0;
unsigned long ultimaTentativaMQTT = 0;
unsigned long ultimoTesteTCP = 0;

// AUXILIARES
void testarLEDInicio() {
  Serial.println("Teste inicial do LED...");
  ledcWrite(PIN_LED, 255);
  delay(500);
  ledcWrite(PIN_LED, 0);
  delay(300);
  ledcWrite(PIN_LED, 255);
  delay(500);
  ledcWrite(PIN_LED, 0);
  Serial.println("Fim do teste inicial do LED.");
}

void conectarWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.println("Conectando ao Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("Wi-Fi conectado!");
    Serial.print("IP do ESP32: ");
    Serial.println(WiFi.localIP());
    Serial.print("RSSI: ");
    Serial.println(WiFi.RSSI());
  } else {
    Serial.println("Falha ao conectar no Wi-Fi.");
  }
}

bool testarTCPBroker() {
  WiFiClient teste;
  Serial.print("Testando TCP em ");
  Serial.print(MQTT_BROKER);
  Serial.print(":");
  Serial.println(MQTT_PORT);

  bool ok = teste.connect(MQTT_BROKER, MQTT_PORT);
  if (ok) {
    Serial.println("TCP com broker OK.");
    teste.stop();
    return true;
  } else {
    Serial.println("Falha no TCP com broker.");
    return false;
  }
}

void publicarStatus(const char* status) {
  if (client.connected()) {
    client.publish(TOPIC_STATUS, status, true);
  }
}

int lerLDRMedia(int amostras = 10) {
  long soma = 0;
  for (int i = 0; i < amostras; i++) {
    soma += analogRead(PIN_LDR);
    delay(5);
  }
  return soma / amostras;
}

int calcularBrilhoAutomatico(int leituraLDR) {
  int brilho = map(leituraLDR, 0, 4095, 255, 0);
  return constrain(brilho, 0, 255);
}

void aplicarBrilhoLED(int brilhoAlvo) {
  brilhoFiltrado = (0.8f * brilhoFiltrado) + (0.2f * brilhoAlvo);
  int brilhoFinal = constrain((int)brilhoFiltrado, 0, 255);
  ledcWrite(PIN_LED, brilhoFinal);
}

void callback(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (unsigned int i = 0; i < length; i++) {
    msg += (char)payload[i];
  }

  String topico = String(topic);

  Serial.print("Mensagem recebida [");
  Serial.print(topico);
  Serial.print("]: ");
  Serial.println(msg);

  if (topico == TOPIC_MODE) {
    msg.toLowerCase();

    if (msg == "auto") {
      modoAutomatico = true;
      Serial.println("Modo alterado para AUTOMÁTICO");
    } else if (msg == "manual") {
      modoAutomatico = false;
      Serial.println("Modo alterado para MANUAL");
    }
  }

  if (topico == TOPIC_LED_MANUAL) {
    int valor = msg.toInt();
    brilhoManual = constrain(valor, 0, 255);
    Serial.print("Brilho manual ajustado para: ");
    Serial.println(brilhoManual);
  }
}

void tentarReconectarMQTT() {
  if (client.connected()) return;
  if (millis() - ultimaTentativaMQTT < 2000) return;

  ultimaTentativaMQTT = millis();

  Serial.print("Conectando ao MQTT... ");

  String clientId = "ESP32-LDR-";
  clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

  bool conectado = false;


  conectado = client.connect(clientId.c_str());

  if (conectado) {
    Serial.println("conectado!");
    publicarStatus("online");
    client.subscribe(TOPIC_MODE);
    client.subscribe(TOPIC_LED_MANUAL);
    Serial.println("Inscrito nos tópicos de comando.");
  } else {
    Serial.print("falhou, rc=");
    Serial.println(client.state());
  }
}

// SETUP
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(PIN_LDR, INPUT);

  bool ok = ledcAttach(PIN_LED, PWM_FREQ, PWM_RES);
  if (!ok) {
    Serial.println("Erro ao configurar PWM no LED!");
    while (true) {
      delay(1000);
    }
  }

  ledcWrite(PIN_LED, 0);

  testarLEDInicio();   // testa se LED/pino/fiação estão corretos
  conectarWiFi();

  client.setServer(MQTT_BROKER, MQTT_PORT);
  client.setCallback(callback);

  Serial.println("Sistema iniciado.");
}

// LOOP
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    conectarWiFi();
  }

  // Teste TCP periódico para diagnosticar se o broker está acessível
  if (WiFi.status() == WL_CONNECTED && millis() - ultimoTesteTCP >= 8000) {
    ultimoTesteTCP = millis();
    testarTCPBroker();
  }

  // Tenta MQTT sem travar o resto do sistema
  if (WiFi.status() == WL_CONNECTED && !client.connected()) {
    tentarReconectarMQTT();
  }

  if (client.connected()) {
    client.loop();
  }

  // Controle manual do LED sempre funciona, mesmo com falha de conexão ao MQTT
  if (millis() - ultimoControle >= 100) {
    ultimoControle = millis();

    int leituraLDR = lerLDRMedia(8);
    int brilhoAlvo = 0;

    if (modoAutomatico) {
      brilhoAlvo = calcularBrilhoAutomatico(leituraLDR);
    } else {
      brilhoAlvo = brilhoManual;
    }

    aplicarBrilhoLED(brilhoAlvo);

    Serial.print("LDR: ");
    Serial.print(leituraLDR);
    Serial.print(" | Brilho alvo: ");
    Serial.print(brilhoAlvo);
    Serial.print(" | WiFi: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? "OK" : "OFF");
    Serial.print(" | MQTT: ");
    Serial.println(client.connected() ? "OK" : "OFF");
  }

  // Publica só se MQTT estiver conectado
  if (client.connected() && millis() - ultimaPublicacao >= 2000) {
    ultimaPublicacao = millis();

    int leituraLDR = lerLDRMedia(8);
    int brilhoAtual = modoAutomatico ? calcularBrilhoAutomatico(leituraLDR) : brilhoManual;

    char msgLdr[16];
    char msgLed[16];

    snprintf(msgLdr, sizeof(msgLdr), "%d", leituraLDR);
    snprintf(msgLed, sizeof(msgLed), "%d", brilhoAtual);

    client.publish(TOPIC_LDR, msgLdr);
    client.publish(TOPIC_LED, msgLed);
  }
}