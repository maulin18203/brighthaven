/*
 * ╔══════════════════════════════════════════════════════════╗
 * ║          BrightHaven — ESP8266 Blynk + MQTT + LED       ║
 * ║                                                          ║
 * ║  Virtual Pin → Device → GPIO mapping:                   ║
 * ║   V0 → Main Room Fan    → GPIO5  (D1)                   ║
 * ║   V1 → Main Room Light  → GPIO4  (D2)                   ║
 * ║   V2 → Main Room TV     → GPIO14 (D5)                   ║
 * ║   V3 → Main Room WiFi   → GPIO12 (D6)                   ║
 * ║   V4 → Bedroom1 Fan     → GPIO13 (D7)                   ║
 * ║   V5 → Bedroom1 Light   → GPIO15 (D8)                   ║
 * ║   V6 → Bedroom1 AC      → GPIO16 (D0)                   ║
 * ║   V7 → Bedroom1 TV      → GPIO2  (D4) <— CONFLICTS W/ LED║
 * ║   V8 → Bedroom1 Geyser  → GPIO0  (D3)                   ║
 * ╚══════════════════════════════════════════════════════════╝
 */

#define BLYNK_TEMPLATE_ID "TMPL3wjTF3gGK"
#define BLYNK_TEMPLATE_NAME "BrightHaven"
#define BLYNK_AUTH_TOKEN "PMgqRecE-oaYV9i_Hqxb8q8kSEemXqRO"

#include <ESP8266WiFi.h>
#include <BlynkSimpleEsp8266.h>
#include <PubSubClient.h> 

const char* WIFI_SSID = "MK";
const char* WIFI_PASS = "9712418203";

// MQTT Broker Settings
const char* mqtt_broker = "broker.hivemq.com";
const int mqtt_port = 1883; 
const char* mqtt_topic_prefix = "brighthaven/relay/";

// Status LED Pin (Built-in Blue LED is usually GPIO2)
#define STATUS_LED LED_BUILTIN 

// GPIO Pin Map
const int PINS[] = { 5, 4, 14, 12, 13, 15, 16, 2, 0 };
#define NUM_PINS 9

BlynkTimer timer;
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// --- Helper to set relay state (Active LOW logic) ---
void setRelay(int index, int state, String source) {
  if (index < 0 || index >= NUM_PINS) return;
  
  digitalWrite(PINS[index], state ? LOW : HIGH);
  
  Serial.printf("[Relay Update] V%d on GPIO%d is now %s (Source: %s)\n", 
                index, PINS[index], state ? "ON" : "OFF", source.c_str());

  if (mqttClient.connected()) {
    String stateTopic = String(mqtt_topic_prefix) + index + "/state";
    mqttClient.publish(stateTopic.c_str(), state ? "1" : "0", true); 
  }
}

// --- Status LED Control ---
void updateStatusLED() {
  // Check if WiFi, Blynk, and MQTT are all connected
  bool isFullyConnected = (WiFi.status() == WL_CONNECTED) && Blynk.connected() && mqttClient.connected();

  if (isFullyConnected) {
    // Solid ON when connected. (ESP8266 LED is Active LOW: LOW = ON)
    digitalWrite(STATUS_LED, LOW); 
  } else {
    // Toggle (Blink) LED if anything is disconnected
    int currentState = digitalRead(STATUS_LED);
    digitalWrite(STATUS_LED, !currentState);
  }
}

// --- MQTT Callback ---
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String topicStr = String(topic);
  String msg = "";
  for (unsigned int i = 0; i < length; i++) {
    msg += (char)payload[i];
  }
  
  Serial.printf("[MQTT] Message arrived: %s, payload: %s\n", topic, msg.c_str());

  if (topicStr.startsWith(mqtt_topic_prefix) && topicStr.endsWith("/set")) {
    int indexStart = String(mqtt_topic_prefix).length();
    int indexEnd = topicStr.lastIndexOf("/");
    String indexStr = topicStr.substring(indexStart, indexEnd);
    int relayIndex = indexStr.toInt();

    int newState = msg.toInt(); 
    
    setRelay(relayIndex, newState, "MQTT");
    Blynk.virtualWrite(V0 + relayIndex, newState);
  }
}

// --- MQTT Reconnect Routine ---
void reconnectMQTT() {
  static unsigned long lastReconnectAttempt = 0;
  if (!mqttClient.connected()) {
    unsigned long now = millis();
    if (now - lastReconnectAttempt > 5000) {
      lastReconnectAttempt = now;
      Serial.print("[MQTT] Attempting connection...");
      
      String clientId = "BrightHaven-ESP8266-";
      clientId += String(random(0xffff), HEX);
      
      if (mqttClient.connect(clientId.c_str())) {
        Serial.println(" connected ✅");
        String subTopic = String(mqtt_topic_prefix) + "+/set";
        mqttClient.subscribe(subTopic.c_str());
      } else {
        Serial.printf(" failed, rc=%d. Trying again later...\n", mqttClient.state());
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n[BrightHaven] System Starting...");

  // Setup the built-in LED
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, HIGH); // Start with LED OFF

  // Initialize Relays to OFF
  for (int i = 0; i < NUM_PINS; i++) {
    digitalWrite(PINS[i], HIGH); 
    pinMode(PINS[i], OUTPUT);
    Serial.printf("Initialized GPIO %d to OFF\n", PINS[i]);
  }

  // Set a timer to update the LED status every 500ms (0.5 seconds)
  timer.setInterval(500L, updateStatusLED);

  // Connect to WiFi and Blynk
  Blynk.begin(BLYNK_AUTH_TOKEN, WIFI_SSID, WIFI_PASS);
  
  Serial.println("[System] WiFi Connected!");
  Serial.print("[System] IP Address: ");
  Serial.println(WiFi.localIP());

  // Setup MQTT
  mqttClient.setServer(mqtt_broker, mqtt_port);
  mqttClient.setCallback(mqttCallback);
}

void loop() {
  Blynk.run();
  timer.run(); // This runs the LED blinking routine automatically
  
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      reconnectMQTT();
    }
    mqttClient.loop();
  }
}

// --- Blynk Pin Mappings ---
BLYNK_WRITE(V0) { setRelay(0, param.asInt(), "Blynk"); }
BLYNK_WRITE(V1) { setRelay(1, param.asInt(), "Blynk"); }
BLYNK_WRITE(V2) { setRelay(2, param.asInt(), "Blynk"); }
BLYNK_WRITE(V3) { setRelay(3, param.asInt(), "Blynk"); }
BLYNK_WRITE(V4) { setRelay(4, param.asInt(), "Blynk"); }
BLYNK_WRITE(V5) { setRelay(5, param.asInt(), "Blynk"); }
BLYNK_WRITE(V6) { setRelay(6, param.asInt(), "Blynk"); }
BLYNK_WRITE(V7) { setRelay(7, param.asInt(), "Blynk"); }
BLYNK_WRITE(V8) { setRelay(8, param.asInt(), "Blynk"); }

BLYNK_CONNECTED() {
  Serial.println("[Blynk] Cloud Connection Established ✅");
  Blynk.syncAll(); 
}