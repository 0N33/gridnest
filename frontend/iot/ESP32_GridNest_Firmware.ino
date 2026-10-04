/*
  GridNest Cyber-Physical Smart Grid Twin — ESP32 Hardware Firmware
  Measures Transformer (Zone B TX_102) and Consumer (Zone B CONS_S_001)
  Voltages, Currents, Active Powers, and System Power Loss.
  
  Streams data via:
  1. Serial Monitor (115200 baud) -> Compatible with iot_serial_bridge.py
  2. WiFi HTTP POST -> Directly pushes JSON to http://<LAPTOP_IP>:8000/api/iot/telemetry
  3. Adafruit IO MQTT / REST -> Compatible with adafruit_bridge.py
*/

#include <WiFi.h>
#include <HTTPClient.h>

// =========================================================================
// 1. NETWORK & CLOUD CONFIGURATION
// =========================================================================
// Set to true if you want the ESP32 to directly send WiFi HTTP POST packets
const bool ENABLE_WIFI = false; 
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// IP address of the laptop running GridNest (Find using 'ipconfig' on Windows or 'ifconfig' on Mac)
const char* GRIDNEST_SERVER_URL = "http://192.168.1.100:8000/api/iot/telemetry";

// Optional: Adafruit IO configuration (for your friend's broker)
const char* AIO_USERNAME = "YOUR_ADAFRUIT_USERNAME";
const char* AIO_KEY      = "YOUR_ADAFRUIT_AIO_KEY";

// Target Digital Twin IDs (Zone B)
const char* TARGET_TRANSFORMER = "TX_102";     // Zone B Transformer
const char* TARGET_CONSUMER    = "CONS_S_001"; // Zone B House

// =========================================================================
// 2. PIN CONFIGURATION & CALIBRATION FACTORS
// =========================================================================
const int transVoltagePin = 35;
const int transCurrentPin = 34;
const int consVoltagePin  = 33;
const int consCurrentPin  = 32;

// Calibration Factors
const float TRANS_V_CAL     = 0.9307; 
const float TRANS_C_INTER   = 10558.05; 
const float TRANS_C_SLOPE   = -10.758;  

const float CONS_V_CAL      = 0.9012; 
const float CONS_C_INTER    = 10833.39; 
const float CONS_C_SLOPE    = -10.961;  

// Energy Tracking Variables
unsigned long lastTime = 0;
float transEnergy_Wh = 0.0;
float consEnergy_Wh = 0.0;
unsigned long lastHttpPostTime = 0;

void setup() {
  Serial.begin(115200);
  pinMode(transVoltagePin, INPUT);
  pinMode(transCurrentPin, INPUT);
  pinMode(consVoltagePin, INPUT);
  pinMode(consCurrentPin, INPUT);

  if (ENABLE_WIFI) {
    Serial.print("[WiFi] Connecting to ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      Serial.print(".");
      attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\n[WiFi] Connected! IP Address: ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("\n[WiFi] Connection timeout. Continuing in Serial-only mode.");
    }
  }

  lastTime = millis();
}

float getAveragedADC(int pin) {
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogRead(pin);
    delay(2);
  }
  return sum / 20.0;
}

void loop() {
  // 1. Read Raw ADC Values
  float transV_Raw = getAveragedADC(transVoltagePin);
  float transC_Raw = getAveragedADC(transCurrentPin);
  float consV_Raw  = getAveragedADC(consVoltagePin);
  float consC_Raw  = getAveragedADC(consCurrentPin);

  // 2. Calculate Voltages & Currents
  float transVoltage = (transV_Raw / 4095.0) * 3.3 * 5.0 * TRANS_V_CAL;
  if (transVoltage < 0.1) transVoltage = 0.0;
  
  float transCurrent = TRANS_C_INTER + (TRANS_C_SLOPE * transC_Raw);
  if (transCurrent < 30 && transCurrent > -30) transCurrent = 0.0;
  transCurrent = abs(transCurrent); // Ensure positive reading

  float consVoltage = (consV_Raw / 4095.0) * 3.3 * 5.0 * CONS_V_CAL;
  if (consVoltage < 0.1) consVoltage = 0.0;

  float consCurrent = CONS_C_INTER + (CONS_C_SLOPE * consC_Raw);
  if (consCurrent < 30 && consCurrent > -30) consCurrent = 0.0;
  consCurrent = abs(consCurrent);

  // 3. Calculate Time Elapsed (in hours for Watt-hours)
  unsigned long currentTime = millis();
  float deltaTime_hours = (currentTime - lastTime) / 3600000.0; 
  lastTime = currentTime;

  // 4. Calculate Power (Watts) -> Current is divided by 1000 to convert mA to A
  float transPower_W = transVoltage * (transCurrent / 1000.0);
  float consPower_W  = consVoltage * (consCurrent / 1000.0);
  
  float powerLoss_W = transPower_W - consPower_W;
  if (powerLoss_W < 0.0) powerLoss_W = 0.0; 

  // 5. Accumulate Energy (Watt-hours)
  transEnergy_Wh += (transPower_W * deltaTime_hours);
  consEnergy_Wh  += (consPower_W * deltaTime_hours);
  
  float energyLoss_Wh = transEnergy_Wh - consEnergy_Wh;
  if (energyLoss_Wh < 0.0) energyLoss_Wh = 0.0;

  // 6. Print Serial Output (Matches Serial Bridge Regex)
  Serial.println("--- SYSTEM STATUS ---");
  Serial.print("Transformer -> ");
  Serial.print(transVoltage); Serial.print("V  |  ");
  Serial.print(transCurrent); Serial.print("mA  |  ");
  Serial.print(transPower_W); Serial.print("W  |  ");
  Serial.print(transEnergy_Wh, 4); Serial.println("Wh");

  Serial.print("Consumer    -> ");
  Serial.print(consVoltage); Serial.print("V  |  ");
  Serial.print(consCurrent); Serial.print("mA  |  ");
  Serial.print(consPower_W); Serial.print("W  |  ");
  Serial.print(consEnergy_Wh, 4); Serial.println("Wh");

  Serial.print("SYSTEM LOSS -> Power Loss: ");
  Serial.print(powerLoss_W);
  Serial.print("W  |  Cumulative Energy Loss: ");
  Serial.print(energyLoss_Wh, 4);
  Serial.println("Wh\n");

  // 7. Optional: Send Direct HTTP POST over WiFi if enabled
  if (ENABLE_WIFI && WiFi.status() == WL_CONNECTED && (currentTime - lastHttpPostTime >= 1000)) {
    lastHttpPostTime = currentTime;
    HTTPClient http;
    http.begin(GRIDNEST_SERVER_URL);
    http.addHeader("Content-Type", "application/json");

    String jsonPayload = "{";
    jsonPayload += "\"transVoltage\":" + String(transVoltage, 2) + ",";
    jsonPayload += "\"transCurrent\":" + String(transCurrent, 2) + ",";
    jsonPayload += "\"transPower_W\":" + String(transPower_W, 2) + ",";
    jsonPayload += "\"transEnergy_Wh\":" + String(transEnergy_Wh, 4) + ",";
    jsonPayload += "\"consVoltage\":" + String(consVoltage, 2) + ",";
    jsonPayload += "\"consCurrent\":" + String(consCurrent, 2) + ",";
    jsonPayload += "\"consPower_W\":" + String(consPower_W, 2) + ",";
    jsonPayload += "\"consEnergy_Wh\":" + String(consEnergy_Wh, 4) + ",";
    jsonPayload += "\"powerLoss_W\":" + String(powerLoss_W, 2) + ",";
    jsonPayload += "\"energyLoss_Wh\":" + String(energyLoss_Wh, 4) + ",";
    jsonPayload += "\"target_consumer_id\":\"" + String(TARGET_CONSUMER) + "\",";
    jsonPayload += "\"target_transformer_id\":\"" + String(TARGET_TRANSFORMER) + "\"";
    jsonPayload += "}";

    int httpResponseCode = http.POST(jsonPayload);
    if (httpResponseCode > 0) {
      Serial.printf("[HTTP] Synced to GridNest (Code %d)\n", httpResponseCode);
    } else {
      Serial.printf("[HTTP] Error sending POST: %d\n", httpResponseCode);
    }
    http.end();
  }

  delay(1000); 
}
