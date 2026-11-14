# Cloud setup (B), all in the AWS console, region us-east-1

Do these in order. Total time is about 60–90 minutes. Each step ends with a test, so you know it works before moving on.

## 1. DynamoDB: two tables (5 min)

DynamoDB → Tables → **Create table**, twice:

| Table name | Partition key | Sort key |
| --- | --- | --- |
| `BreatheReadings` | `deviceId` (String) | `ts` (Number) |
| `BreatheState` | `deviceId` (String) | none |

Keep the default settings and create both.

## 2. SNS: alert topic (5 min)

1. SNS → Topics → **Create topic** → Standard → name `breathe-alerts`. Copy its **ARN**.
2. **Create subscription** → protocol **Email** → your email. Do this for each teammate, then click the confirm link in each inbox.

About text messages: since 2023, US texts from AWS have needed a registered toll-free or 10DLC number, which takes days to approve. **Use email as the main alert.** The phone's mail notification is your "buzz" in the demo. You can also try an SMS subscription, but don't count on it.

## 3. Lambda: breathe-risk (10 min)

1. Lambda → **Create function** → Author from scratch → name `breathe-risk`, runtime **Python 3.12** → Create.
2. Paste `risk_lambda/lambda_function.py` into the code editor → **Deploy**.
3. Configuration → **Environment variables** → add:
   - `READINGS_TABLE` = `BreatheReadings`
   - `STATE_TABLE` = `BreatheState`
   - `ALERT_TOPIC_ARN` = the ARN from step 2
   - `KID_NAMES` = `{"kid-001": "Jayden"}`
4. Configuration → **Permissions** → click the role name → **Add permissions → Attach policies** → `AmazonDynamoDBFullAccess` and `AmazonSNSFullAccess`. These are broad, which is fine for a weekend demo.
5. **Test it:** Test tab → new event with this JSON → Test:
   ```json
   {"deviceId": "kid-001", "ts": 0, "tvoc": 700, "eco2": 900, "tempC": 22, "humidity": 40, "kind": "telemetry"}
   ```
   It should return `"risk": "red", "alerted": true`, you should get an email, and both tables should have a row.

## 4. IoT Core: the device's identity (15 min)

1. IoT Core → Security → **Policies → Create policy** → name `breathe-device-policy` → JSON editor:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Effect": "Allow", "Action": ["iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive"], "Resource": "*" }
     ]
   }
   ```
   (`"*"` is wide open. That's fine for a demo, but tighten it before anything real.)
2. IoT Core → Manage → **Things → Create things** → single thing → name `kid-001` → **Auto-generate a new certificate** → attach `breathe-device-policy` → Create.
3. **Download all the files on the screen that appears, right away.** The private key can only be downloaded on this screen:
   - Device certificate (`...-certificate.pem.crt`)
   - Private key (`...-private.pem.key`)
   - Amazon Root CA 1 (`AmazonRootCA1.pem`)

   Send them to A privately (not through GitHub). A pastes them into `firmware/breathe_device/secrets.h`.
4. IoT Core → **Settings** → copy the **Device data endpoint** (`xxxx-ats.iot.us-east-1.amazonaws.com`) for A's `secrets.h`. The CLI command `aws iot describe-endpoint --endpoint-type iot:Data-ATS` gives the same value.

## 5. IoT Rule: route messages to the Lambda (5 min)

1. IoT Core → Message routing → **Rules → Create rule** → name `breathe_to_lambda`.
2. SQL statement (version 2016-03-23):
   ```sql
   SELECT *, topic(3) AS kind FROM 'breathe/+/+'
   ```
3. Action → **Lambda** → `breathe-risk` → Create. The console adds the permission it needs automatically.
4. **Test it:** IoT Core → **MQTT test client** → Publish to a topic → topic `breathe/kid-001/telemetry` → message:
   ```json
   {"deviceId": "kid-001", "ts": 0, "tvoc": 150, "eco2": 500, "tempC": 21, "humidity": 45}
   ```
   Check that a new row appears in `BreatheReadings` with `risk = green`. Then publish to `breathe/kid-001/puff`:
   ```json
   {"deviceId": "kid-001", "ts": 0, "event": "puff"}
   ```
   If nothing shows up, check the Lambda's logs under Monitor → View CloudWatch logs.

## 6. Lambda: breathe-api (10 min)

1. Create function `breathe-api`, Python 3.12, and paste `api_lambda/lambda_function.py` → Deploy.
2. Environment variables: `READINGS_TABLE` = `BreatheReadings`, `STATE_TABLE` = `BreatheState`.
3. Configuration → General → **Timeout = 15 seconds**. Bedrock can take a few seconds.
4. Permissions → role → attach `AmazonDynamoDBReadOnlyAccess`. For the Bedrock summary, also attach `AmazonBedrockFullAccess`.

## 7. API Gateway: HTTP API (10 min)

1. API Gateway → **Create API → HTTP API → Build** → Add integration → Lambda → `breathe-api` → name `breathe-http`.
2. Routes. Add all three, each pointing to `breathe-api`:
   - `GET /status/{deviceId}`
   - `GET /kids`
   - `GET /summary/{deviceId}`
3. Stage: `$default` with auto-deploy on → Create.
4. Left menu → **CORS** → Access-Control-Allow-Origin `*`, Allow methods `GET` → Save.
5. Copy the **Invoke URL** (`https://abc123.execute-api.us-east-1.amazonaws.com`) and give it to C.
6. **Test it:** open `<Invoke URL>/status/kid-001` and `<Invoke URL>/kids` in a browser. You should see JSON.

## 8. Bedrock summary (stretch goal, 15 min)

1. Bedrock console → **Model access** → request access to one text model (for example a Claude or Amazon Nova model).
2. Copy that model's **ID**. If invoking it complains that on-demand throughput isn't supported, use its **inference profile ID** instead (it starts with `us.`).
3. On `breathe-api`, add env var `MODEL_ID` = that ID.
4. **Test it:** open `<Invoke URL>/summary/kid-001` in a browser.

## 9. C's wristband login

The wristband script publishes puffs from C's laptop using C's AWS CLI login. Attach the `AWSIoTDataAccess` policy to C's IAM user.

## Set a billing alarm

Billing → Budgets → Create budget → **zero-spend** or $10 budget → your email. This weekend should cost close to $0.
