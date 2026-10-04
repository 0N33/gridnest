/*
 * GridNest Smart Grid Digital Twin — ESP32 Physical Hardware Prototype
 * Connects to Adafruit IO MQTT Broker (io.adafruit.com:1883)
 *
 * Hardware Wiring:
 * - Transformer Voltage Sensor:  GPIO 35 (transVoltagePin)
 * - Transformer Current Sensor:  GPIO 34 (transCurrentPin)
 * - Consumer Voltage Sensor:     GPIO 33 (consVoltagePin)
 * - Consumer Current Sensor:     GPIO 32 (consCurrentPin)
 *
 * Requires Arduino Libraries:
 * - PubSubClient (by Nick O'Leary)
 * - WiFi (built-in ESP32 core)
 */

#include <WiFi.h>
#include <PubSubClient.h>

// =========================================================================
// 1. NETWORK & ADAFRUIT IO CONFIGURATION
// =========================================================================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";         // Enter your WiFi Network Name
const char* WIFI_PASS     = "YOUR_WIFI_PASSWORD";     // Enter your WiFi Password

const char* AIO_SERVER    = "io.adafruit.com";
const int   AIO_PORT      = 1883;                     // Standard unencrypted MQTT port (or 8883 for SSL)
const char* AIO_USERNAME  = "YOUR_AIO_USERNAME";      // Enter your Adafruit IO Username
const char* AIO_KEY       = "aio_YOUR_ACTIVE_KEY";    // Enter your Adafruit IO Key

// Adafruit IO Feed Topic: {username}/feeds/{feed_name}
// Create a feed called "smartgrid" on io.adafruit.com
const char* AIO_FEED_SUB  = "smartgrid"; 

// =========================================================================
// 2. PIN CONFIGURATION & CALIBRATION FACTORS
// =========================================================================
const int transVoltagePin = 35;
const int transCurrentPin = 34;
const int consVoltagePin  = 33;
const int consCurrentPin  = 32;

// Exact calibration constants from your prototype bench test
const float TRANS_V_CAL   = 0.9307;
const float TRANS_C_INTER = 10558.05;
const float TRANS_C_SLOPE = -10.758;

const float CONS_V_CAL    = 0.9012;
const float CONS_C_INTER  = 10833.39;
const float CONS_C_SLOPE  = -10.961;

// Energy tracking accumulators
unsigned long lastTime = 0;
unsigned long lastMQTTSend = 0;
float transEnergy_Wh = 0.0;
float consEnergy_Wh  = 0.0;

WiFiClient espClient;
PubSubClient mqttClient(espClient);
char mqttTopic[128];

// =========================================================================
// 3. UTILITY FUNCTIONS
// =========================================================================
float getAveragedADC(int pin) {
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogRead(pin);
    delay(2);
  }
  return sum / 20.0;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("\nConnecting to WiFi '");
  Serial.print(WIFI_SSID);
  Serial.print("'");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 25) {
    delay(500);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[WiFi] Connection timeout. Retrying in main loop...");
  }
}

void connectMQTT() {
  if (mqttClient.connected()) return;
  connectWiFi();

  Serial.print("[MQTT] Connecting to io.adafruit.com as ");
  Serial.println(AIO_USERNAME);

  String clientId = "ESP32_GridNest_" + String(random(0xffff), HEX);
  if (mqttClient.connect(clientId.c_str(), AIO_USERNAME, AIO_KEY)) {
    Serial.println("[MQTT] Connected to Adafruit IO successfully!");
  } else {
    Serial.print("[MQTT] Failed, state rc=");
    Serial.print(mqttClient.state());
    Serial.println(" (Will retry in next cycle)");
  }
}

// =========================================================================
// 4. ARDUINO SETUP
// =========================================================================
void setup() {
  Serial.begin(115200);
  pinMode(transVoltagePin, INPUT);
  pinMode(transCurrentPin, INPUT);
  pinMode(consVoltagePin, INPUT);
  pinMode(consCurrentPin, INPUT);

  analogReadResolution(12); // ESP32 12-bit ADC (0 - 4095)

  lastTime = millis();
  lastMQTTSend = millis();

  // Build Adafruit IO Topic: {AIO_USERNAME}/feeds/smartgrid
  snprintf(mqttTopic, sizeof(mqttTopic), "%s/feeds/%s", AIO_USERNAME, AIO_FEED_SUB);

  mqttClient.setServer(AIO_SERVER, AIO_PORT);
  mqttClient.setBufferSize(512); // Ensure JSON packet fits in buffer

  connectWiFi();
  connectMQTT();
}

// =========================================================================
// 5. MAIN EXECUTION LOOP
// =========================================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  // 1. Read Raw ADC Values
  float transV_Raw = getAveragedADC(transVoltagePin);
  float transC_Raw = getAveragedADC(transCurrentPin);
  float consV_Raw  = getAveragedADC(consVoltagePin);
  float consC_Raw  = getAveragedADC(consCurrentPin);

  // 2. Calculate Physical Voltages & Currents
  float transVoltage = (transV_Raw / 4095.0) * 3.3 * 5.0 * TRANS_V_CAL;
  if (transVoltage < 0.1) transVoltage = 0.0;

  float transCurrent = TRANS_C_INTER + (TRANS_C_SLOPE * transC_Raw);
  if (transCurrent < 30 && transCurrent > -30) transCurrent = 0.0;
  transCurrent = abs(transCurrent); // Ensure positive reading (mA)

  float consVoltage = (consV_Raw / 4095.0) * 3.3 * 5.0 * CONS_V_CAL;
  if (consVoltage < 0.1) consVoltage = 0.0;

  float consCurrent = CONS_C_INTER + (CONS_C_SLOPE * consC_Raw);
  if (consCurrent < 30 && consCurrent > -30) consCurrent = 0.0;
  consCurrent = abs(consCurrent); // (mA)

  // 3. Calculate Time Elapsed (hours)
  unsigned long currentTime = millis();
  float deltaTime_hours = (currentTime - lastTime) / 3600000.0;
  lastTime = currentTime;

  // 4. Calculate Power (Watts) -> Current in mA converted to A (/ 1000.0)
  float transPower_W = transVoltage * (transCurrent / 1000.0);
  float consPower_W  = consVoltage * (consCurrent / 1000.0);

  float powerLoss_W = transPower_W - consPower_W;
  if (powerLoss_W < 0.0) powerLoss_W = 0.0; // Prevent sensor noise negative loss

  // 5. Accumulate Energy (Watt-hours)
  transEnergy_Wh += (transPower_W * deltaTime_hours);
  consEnergy_Wh  += (consPower_W * deltaTime_hours);

  float energyLoss_Wh = transEnergy_Wh - consEnergy_Wh;
  if (energyLoss_Wh < 0.0) energyLoss_Wh = 0.0;

  // 6. Print Serial Diagnostics
  Serial.println("--- SYSTEM STATUS ---");
  Serial.printf("Transformer -> %5.1fV | %6.1fmA | %6.1fW | %7.4fWh\n", transVoltage, transCurrent, transPower_W, transEnergy_Wh);
  Serial.printf("Consumer    -> %5.1fV | %6.1fmA | %6.1fW | %7.4fWh\n", consVoltage, consCurrent, consPower_W, consEnergy_Wh);
  Serial.printf("SYSTEM LOSS -> Power Loss: %.2f W | Cumulative Energy Loss: %.4f Wh\n\n", powerLoss_W, energyLoss_Wh);

  // 7. Publish to Adafruit IO every 2500ms (Safe for Adafruit IO Free tier limit: 30 requests/min)
  if (currentTime - lastMQTTSend >= 2500) {
    lastMQTTSend = currentTime;

    // Construct JSON Payload for GridNest Digital Twin
    char payload[384];
    snprintf(payload, sizeof(payload),
      "{\"transVoltage\":%.2f,\"transCurrent\":%.2f,\"transPower\":%.2f,\"transEnergy\":%.4f,"
      "\"consVoltage\":%.2f,\"consCurrent\":%.2f,\"consPower\":%.2f,\"consEnergy\":%.4f,"
      "\"powerLoss\":%.2f,\"energyLoss\":%.4f}",
      transVoltage, transCurrent, transPower_W, transEnergy_Wh,
      consVoltage, consCurrent, consPower_W, consEnergy_Wh,
      powerLoss_W, energyLoss_Wh
    );

    if (mqttClient.connected()) {
      bool sent = mqttClient.publish(mqttTopic, payload);
      if (sent) {
        Serial.printf("[Adafruit IO] Packet published to %s: %s\n", mqttTopic, payload);
      } else {
        Serial.println("[Adafruit IO] Publish failed (packet dropped)");
      }
    }
  }

  delay(200); // Sampling loop rate
}
