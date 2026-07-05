# User Guide: Welcome to TradeVed!
## Your No-Nonsense Guide to Testing Trading Ideas Without the Hype

Welcome! If you've ever seen a social media video promising a "99% win-rate secret formula" or wanted to know if a simple trading idea actually makes money, you're in the right place. 

TradeVed is a platform designed to let you test trading rules on real historical market data (a process called **backtesting**) and see how they survive historical market crashes or future uncertainties (a process called **stress testing**).

You don't need a degree in finance or any programming knowledge to use TradeVed. This guide will walk you through everything you need to know.

---

## 1. Core Concepts (Explain Like I'm 5)

Before we press any buttons, let's understand three basic terms:

*   **What is a Backtest?**  
    Imagine you have a rule: *"Buy a stock every Monday morning and sell it every Friday evening."* A backtest goes back in time (say, over the last 5 years) and simulates exactly what would have happened if you followed that rule. It tells you how much money you would have made or lost.
*   **What is a Stress Test?**  
    A strategy might make money in normal times, but what happens during a panic? A stress test simulates historical crises (like the 2008 financial crash or the 2020 COVID crash) or generates hundreds of random market paths (Monte Carlo simulations) to see if your strategy would have wiped out your account.
*   **What is an Honest Backtest?**  
    Many online backtesters cheat. They assume you can buy and sell instantly for free. TradeVed is different: it automatically deducts realistic commissions, exchange charges, and government taxes (such as Indian Budget 2024 tax rates). If a strategy is ruined by fees, TradeVed will show you.

---

## 2. Our Built-In Strategies (Made Simple)

TradeVed has three classic trading methods pre-configured, plus dozens of indicator presets. Here is how the classic ones work:

### A. The Grid Strategy
Imagine a price grid on a chart. You draw lines above and below the current price.
*   **How it works:** When the price falls down through a line, the system buys. When the price rises up through a line, the system sells.
*   **Best for:** Markets that are bouncing up and down in a flat range (sideways markets).
*   **Warning:** If the price drops off a cliff and never comes back, you will keep buying all the way down and suffer heavy losses.

### B. The DCA (Dollar Cost Averaging) Strategy
*   **How it works:** Instead of trying to guess when the price is lowest, you invest a fixed amount of money at regular intervals (e.g., every 24 hours).
*   **Best for:** Long-term investing in assets that generally go up over time (like Bitcoin or major stock indexes).
*   **Benefit:** You buy more shares when the price is cheap, and fewer when it is expensive, averaging out your costs.

### C. The PLA (Progressive Level Averaging) Strategy
*   **How it works:** First, it waits for a trend indicator (an EMA crossover) to confirm the price is moving up. Once in, if the price temporarily dips, it buys more at lower levels (cascades) to lower your average purchase price.
*   **Best for:** Trending markets where you want to buy pullbacks.

---

## 3. Step-by-Step Walkthroughs

### 3.1 Step 1: Running Your First Backtest
Let's test a simple DCA strategy on Bitcoin:

1.  Open the **Backtest** page (the default screen).
2.  On the left panel, select **DCA** from the Strategy dropdown.
3.  Set the **Symbol** to `BTC/USDT` (Bitcoin).
4.  Set your starting capital (e.g., `10000` dollars).
5.  Set your start and end dates (e.g., `2022-01-01` to `2024-01-01`).
6.  Look at the strategy parameters. Set the **Buy Interval** to `24` (meaning buy every 24 hours) and **Invest per Buy** to `100` dollars.
7.  Click the ⚡ **Smart Fill** button. This automatically checks the asset price and fills in appropriate capital scales if your parameters are out of bounds.
8.  Click **Run Backtest**.

Within a second, the results will load on the right.

---

### 3.2 Step 2: Running a Stress Test
Once you've run a backtest, you should see how robust it is.

1.  Click the **Stress Test** tab in the top navigation bar.
2.  If you ran a backtest, click **Use Last Strategy** on the sidebar to pre-fill the form.
3.  Choose a **Scenario**. Let's select **2020 COVID Flash Crash** (this simulates a 34% drop in price followed by a rapid recovery).
4.  Set **Monte Carlo Runs** to `100`. This will simulate 100 slightly different paths of the crash to represent different timings and severities.
5.  Click **Run Stress Test**.
6.  **Watch the Canvas Chart:** You will see a fan of colored lines building up in real-time. This is not a static loading bar — it is a live simulation.

---

### 3.3 Step 3: Extracting Rules from a Reel
Have a video from Instagram or YouTube with a strategy?

1.  Go to the **Reel Backtest** tab.
2.  Select **Pasted Transcript** (recommended if you have the transcript text) or paste the URL.
3.  Paste the text, e.g., *"When the RSI falls below 30, we buy. When the RSI goes above 70, we sell."*
4.  Click **Analyze Reel**.
5.  An AI will read the text, identify the rules, and display them in the **Strategy Editor**.
6.  If the video forgot to mention something (like what stop loss to use), the system will flag a **Gap Alert** (e.g., *"No exit criteria specified"*). 
7.  Click on the gap, choose a value, and click **Compile & Backtest**. The platform will immediately run a historical simulation of that video's claims.

---

## 4. How to Read Your Results (Without a Finance Degree)

When your backtest finishes, you are presented with a **Metrics Grid** and a **Plain Language Verdict**. Here is how to read them:

### The "Rollercoaster" Metrics

| Metric | What it represents | Simple Analogy | Good Value |
| :--- | :--- | :--- | :--- |
| **Total Return** | How much money you made in total. | The destination. | Higher than holding the index. |
| **Max Drawdown** | The biggest peak-to-trough drop in your account value. | The deepest dip on the rollercoaster. | Closer to 0 (under -20% is good). |
| **Sharpe Ratio** | Return adjusted for volatility. | The bumpiness of the road. | Above 1.0 (Excellent is >2.0). |
| **Sortino Ratio** | Return adjusted *only* for bad volatility (drawdowns). | The depth of the potholes. | Above 1.5. |
| **Win Rate** | The percentage of trades that made a profit. | Batting average. | Over 50% (but check profit size!). |
| **Profit Factor** | Total gains divided by total losses. | Money earned per dollar lost. | Above 1.5. |

### The Bumpy Road Analogy: Sharpe vs. Sortino
*   **High Sharpe, Low Max Drawdown:** You are driving a smooth car on a well-paved highway. It feels safe, and your account grows steadily.
*   **Low Sharpe, High Max Drawdown:** You are on a bumpy rollercoaster. You might end up in a profitable place, but the journey was terrifying and you almost jumped off.
*   *Tip:* Always check **Max Drawdown**. If a strategy has a -50% drawdown, ask yourself: *"Will I have the nerve to keep this running when half my money is gone?"* Most people panic-sell at the bottom.

---

## 5. Master the Live Monte Carlo Canvas

During Stress Tests or Forward Tests, the platform streams a "spaghetti chart" of equity lines:

```
▲ Equity
│            .======= (Teal: Profitable Futures)
│         .==:==:==
│      .==:==:==:==== (Yellow: Break-even Paths)
│   .==:==:==:==
│====='=======·====
│   `==:==:==:==
│      `==:==:==:==== (Red: Loss Futures)
│         `==:==:==
▼            `=======
───────────────────────► Time
```

### Pro-Tips for Using the Canvas:
1.  **Rainbow Color Coding:** Paths are colored by their returns. Red paths are losses, yellow are flat, and teal are profitable. A mostly teal fan is a very healthy sign!
2.  **Delta Mode Toggle:** Look at the top-right of the chart. Toggling **Delta Mode** changes the vertical axis to show the percentage impact compared to a normal market baseline. This isolates the stress effect from the general market trend, showing if your strategy actually protects you.
3.  **Hover for Details:** Hover your mouse near any line to see a tooltip containing that specific path's Sharpe ratio, return, and maximum drawdown.
4.  **Click to Pin:** Click any path to pin it. It will turn bright orange and stand out on top. Click again to clear the pin.

---

## 6. Common Mistakes to Avoid

1.  **Overfitting (The "Perfect Past" Trap):** Don't adjust your parameters until you get a perfect 1000% return. A strategy that is tuned perfectly to the past is like studying the answers to yesterday's test — it will fail on tomorrow's test.
2.  **Ignoring the F&O Lot-Size Rule:** If you are testing Indian Futures or Options, you cannot buy fractional shares or small amounts. You must buy in **lots** (e.g., 1 lot of NIFTY50 is 50 units). If you start with ₹10,000, the system will skip buying because 1 lot costs much more. Always use ⚡ **Smart Fill** to ensure your capital matches lot sizes.
3.  **Forgetting Transaction Fees:** A strategy that trades 10 times a day might look profitable on paper, but after paying commissions, GST, and STT, you may end up losing money. Look at the **Fees** column in the trade log!

---

## 7. Troubleshooting & FAQs

### Q: Why does my backtest show "0 Trades"?
*   **Reason 1:** Your capital is too small for Indian Futures/Options. Click ⚡ **Smart Fill** on the sidebar to fix it.
*   **Reason 2:** Your indicators never crossed. For example, if you set "Buy when RSI is below 10", that rarely happens. Try raising the threshold to 30.
*   **Reason 3:** You are using daily candles on a short-term trend strategy (like PLA). Check if your interval is set to Daily when it should be Hourly.

### Q: Why does the Stress Tester say "Failed to Fetch"?
*   This happens if your network disconnects or if Vite proxies timeout. The platform has infinite timeout configurations to prevent this, but check if your local server is still running.

### Q: What is the "Circular Block Bootstrap" fallback?
*   If our AI engine (Kronos) is sleeping or undergoing maintenance, TradeVed automatically swaps in a mathematical bootstrap. It takes blocks of historical data and pieces them together randomly. This ensures you still get 100 realistic future paths without relying on a cloud server.
