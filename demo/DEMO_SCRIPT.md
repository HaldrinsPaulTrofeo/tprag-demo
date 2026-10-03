# T-PRAG demo script (about 8 minutes)

Shows the system's response to the adviser consultation (Recording 9): one online request, a stated basis for allocation, and the office still deciding.

## Before you start

```powershell
python demo/run_demo.py
```

Open `http://127.0.0.1:8800/demo`. Every page shows an amber **DEMONSTRATION** banner. The data is synthetic, in a temporary database, and the real MySQL database is never touched. Stop with Ctrl+C. Everything runs the real application code, so the numbers below come from the actual rule, not a mock-up.

Setup in the demo data: Binan, Sampaloc and Poblacion Uno have six or more past sessions (own history). Sabang, Layugan, Dingin and Lambac have fewer, so they use the municipal distribution.

## 1. One request for everything (adviser: "isang request lang lahat yun")

1. Click **Sign in as a barangay (Binan)**. Land on the request form, not the dashboard.
2. Open the **Category** list: Anti-rabies, Livestock, Seeds, Fingerlings, Agricultural inputs, Other. Pick Seeds: the unit changes to bags and the note says there is no history to support a recommendation.
3. Back on Anti-rabies, enter quantity `25`, submit. Request id shown; it appears under "Your barangay's requests" as SUBMITTED.
4. Point out that the barangay is locked to Binan and cannot view or request for other barangays.

Say: online requests, agriculture and animal side in one queue; paper letters are encoded by staff into the same queue (shown in step 2).

## 2. The municipal queue

1. Go to `/demo`, click **Sign in as the municipal officer**.
2. The queue lists pending requests (anti-rabies, seeds, fingerlings, livestock, one paper letter encoded by staff, shown as `SUBMITTED / letter`).
3. Open **Request to grant chain**. It shows anti-rabies: 9 requests, 595 vials asked (including the 25 you just submitted), 20 recommended, 20 granted. The 20 come from two earlier requests the office already decided (Dingin asked 100, recommended 10, granted 10; Lambac asked 40, recommended 10, granted 10). Percentages compare only requests that reached that stage (14.3%).

Say: this is the 100 to 50 to 30 chain the adviser described, now recorded and measurable. Seeds, fingerlings and livestock show "Not yet": no history, so no number is invented.

## 3. The basis (adviser: "ano yung basis?")

1. In the queue, tick **Poblacion Uno, Binan, Sampaloc, Sabang, Layugan** (anti-rabies) in that order. The order box opens; this is the officer's priority.
2. Enter **200** vials, 75% service level, **Calculate and save recommendations**.
   Result: 52 vials planned, nothing unfunded. Poblacion Uno 15, Binan 10, Sampaloc 7, Sabang 10, Layugan 10. Binding term is **history** every time: these barangays asked for 40 to 100, but their past sessions never needed more.
3. Now enter **35** vials and calculate again.
   Result: 32 vials planned. Poblacion Uno 15, Binan 10 and Sampaloc 7 funded in full. Sabang and Layugan show recommended 3 with binding **available** and are listed as **unfunded**.
4. Click **Review** on Sabang. The panel shows the three terms side by side, why each applies, and the notice "Municipal history is used because local history is insufficient".

Say: recommended = minimum of (what past sessions support, what is left, what was asked). The unfunded barangays are deferred to the next release rather than given a token amount. The office's own position is that a thin spread only lets them say a vaccination was held.

## 4. The office decides (adviser: "sila pa rin ang magde-decide")

1. On Sabang's panel the form is prefilled: DEFERRED, grant 0. This is a suggestion only.
2. Change to **Partially approved**, grant 3, leave the reason empty, save: the system refuses ("A reason is required when granting less than requested").
3. Enter a reason (for example "Officer reserves the remaining 3 vials for the next scheduled session") and save. Reopen the request: the decision, actor and time are kept, and any later override is added to its history.
4. Tick Poblacion Uno and click **Download vaccine request letter**. The letter uses the **requested** quantities, not the grants, so unmet need is visible to the province.

## 5. Where forecasting fits (adviser: "doon kayo mag-focus sa decision support")

State it directly: monthly volume depends on provincial allocation and supply outages, not demand, so the ARIMA forecast loses to a seasonal-naive baseline (MAE 302.7 vs 234.5). That result is why the allocation rule exists. The forecast is kept as a documented negative result and an input, not as the contribution. (The forecast page is part of the full system, not this demo.)

## Questions to expect

| Question | Answer |
|---|---|
| Why not split the shortage evenly? | Thin coverage reaches protective coverage nowhere; the partner office's recorded position. The officer can still override with a reason. |
| Who sets priority? | The officer. The software does not infer vulnerability or assign a hidden ranking. |
| Is the stock figure live inventory? | No. It is an officer-entered planning figure, not a stock ledger. |
| Provincial accounts? | Out of scope: no data-sharing arrangement exists. The data model accepts a provincial tier later. |
| Agriculture recommendations? | Captured only; no historical series exists, so no recommendation is claimed. |
| How accurate is the recommendation? | It is an empirical quantile of 32 recorded sessions, an estimate and not a guarantee. Real-world allocation outcomes have not been measured yet. |

## Not shown in this demo

Charter question answering, document OCR, SMS reminders, the monthly forecast page and the registry. They are separate features of the full system.
