/*
 * ╔══════════════════════════════════════════════════════════════════════════════╗
 * ║                  BrightHaven — ESP32 Ultimate Edition                        ║
 * ║                 (Blynk + MQTT + Instant Flash Memory)                        ║
 * ╠══════════════════════════════════════════════════════════════════════════════╣
 * ║ VIRTUAL PIN │ DEVICE NAME        │ ESP32 GPIO │ DEVKIT V1 PHYSICAL PIN (30p) ║
 * ╟─────────────┼────────────────────┼────────────┼──────────────────────────────╢
 * ║     V0      │ Main Room Fan      │  GPIO 13   │ Left Side, Pin 13  (D13)     ║
 * ║     V1      │ Main Room Light    │  GPIO 14   │ Left Side, Pin 11  (D14)     ║
 * ║     V2      │ Main Room TV       │  GPIO 25   │ Left Side, Pin 8   (D25)     ║
 * ║     V3      │ Main Room WiFi     │  GPIO 26   │ Left Side, Pin 9   (D26)     ║
 * ║     V4      │ Bedroom1 Fan       │  GPIO 27   │ Left Side, Pin 10  (D27)     ║
 * ║     V5      │ Bedroom1 Light     │  GPIO 32   │ Left Side, Pin 6   (D32)     ║
 * ║     V6      │ Bedroom1 AC        │  GPIO 33   │ Left Side, Pin 7   (D33)     ║
 * ║     V7      │ Bedroom1 TV        │  GPIO 4    │ Right Side, Pin 10 (D4)      ║
 * ║     V8      │ Bedroom1 Geyser    │  GPIO 16   │ Right Side, Pin 9  (RX2)     ║
 * ╚══════════════════════════════════════════════════════════════════════════════╝
 * Note: "Left" side is the antenna at the top, USB at the bottom.
 */

#define BLYNK_TEMPLATE_ID "TMPL3n_dCuyOY"
#define BLYNK_TEMPLATE_NAME "BrightHaven1"
#define BLYNK_AUTH_TOKEN "_o11JtMRBfA3QCLcvdpw7YpHKWGpBIcp"

#include <WiFi.h>
#include <BlynkSimpleEsp32.h>
#include <PubSubClient.h>
#include <Preferences.h> // Library to save state to flash memory

const char* WIFI_SSID = "MK";
const char* WIFI_PASS = "9712418203";

// MQTT Broker Settings
const char* mqtt_broker = "broker.hivemq.com";
const int mqtt_port = 1883; 
const char* mqtt_topic_prefix = "brighthaven1/relay/";

// Status LED Pin (ESP32 Built-in Blue LED is GPIO2)
#define STATUS_LED 2 

// Safe ESP32 GPIO Pin Map
const int PINS[] = { 13, 14, 25, 26, 27, 32, 33, 4, 16 };
#define NUM_PINS 9

BlynkTimer timer;
WiFiClient espClient;
PubSubClient mqttClient(espClient);
Preferences preferences; // Create preferences object to handle flash memory

// --- Helper to set relay state (Active LOW logic) ---
void setRelay(int index, int state, String source) {
  if (index < 0 || index >= NUM_PINS) return;
  
  // state 1 (App/MQTT ON) -> LOW (Relay ON)
  // state 0 (App/MQTT OFF) -> HIGH (Relay OFF)
  digitalWrite(PINS[index], state ? LOW : HIGH);
  
  // Save the new state instantly to ESP32 Flash Memory
  preferences.putInt(String(index).c_str(), state);
  
  Serial.printf("[Relay Update] V%d on GPIO%d is now %s (Source: %s)\n", 
                index, PINS[index], state ? "ON" : "OFF", source.c_str());

  // Publish state to MQTT
  if (mqttClient.connected()) {
    String stateTopic = String(mqtt_topic_prefix) + index + "/state";
    mqttClient.publish(stateTopic.c_str(), state ? "1" : "0", true); 
  }
}

// --- Status LED Control ---
void updateStatusLED() {
  bool isFullyConnected = (WiFi.status() == WL_CONNECTED) && Blynk.connected() && mqttClient.connected();

  if (isFullyConnected) {
    digitalWrite(STATUS_LED, HIGH); // Solid ON when fully connected
  } else {
    int currentState = digitalRead(STATUS_LED);
    digitalWrite(STATUS_LED, !currentState); // Blink when disconnected
  }
}

// --- MQTT Callback ---
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String topicStr = String(topic);
  String msg = "";
  for (unsigned int i = 0; i < length; i++) {
    msg += (char)payload[i];
  }
  
  Serial.printf("[MQTT] Command arrived: %s, payload: %s\n", topic, msg.c_str());

  if (topicStr.startsWith(mqtt_topic_prefix) && topicStr.endsWith("/set")) {
    int indexStart = String(mqtt_topic_prefix).length();
    int indexEnd = topicStr.lastIndexOf("/");
    String indexStr = topicStr.substring(indexStart, indexEnd);
    int relayIndex = indexStr.toInt();

    int newState = msg.toInt(); 
    
    setRelay(relayIndex, newState, "MQTT");
    Blynk.virtualWrite(V0 + relayIndex, newState); // Keep Blynk App UI updated
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
      
      String clientId = "BrightHaven-ESP32-";
      clientId += String(random(0xffff), HEX);
      
      if (mqttClient.connect(clientId.c_str())) {
        Serial.println(" connected ✅");
        String subTopic = String(mqtt_topic_prefix) + "+/set";
        mqttClient.subscribe(subTopic.c_str());
      } else {
        Serial.printf(" failed, rc=%d. Retrying later...\n", mqttClient.state());
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n[BrightHaven] ESP32 System Starting...");

  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW); // Start with Blue LED OFF

  // 1. Open Flash Memory namespace "brighthaven" (false = read/write mode)
  preferences.begin("brighthaven", false);

  // 2. Initialize Relays based on LAST SAVED STATE from flash memory
  for (int i = 0; i < NUM_PINS; i++) {
    // Read saved state. If it's the very first boot, default to 0 (App OFF)
    int savedState = preferences.getInt(String(i).c_str(), 0); 
    
    // Safety check: Ensure the pin is set HIGH (OFF) before turning it ON if needed
    digitalWrite(PINS[i], HIGH);
    pinMode(PINS[i], OUTPUT);
    
    // Set the physical pin to match the saved state
    digitalWrite(PINS[i], savedState ? LOW : HIGH); 
    
    Serial.printf("Restored V%d (GPIO %d) to %s from memory\n", i, PINS[i], savedState ? "ON" : "OFF");
  }

  // Set a timer to update the LED status every 500ms
  timer.setInterval(500L, updateStatusLED);

  // Connect to WiFi and Blynk
  Serial.println("[System] Connecting to WiFi...");
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
  timer.run(); 
  
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
  
  // Push our actual flash memory states up to the app so the UI matches reality.
  for(int i = 0; i < NUM_PINS; i++) {
     int savedState = preferences.getInt(String(i).c_str(), 0);
     Blynk.virtualWrite(V0 + i, savedState);
  }
}
