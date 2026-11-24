# Customer guide

This is an independent sample. It is not affiliated with BytePlus.

## What it does

You describe a short video in words, or give a picture to start from. BytePlus
makes the video. This tool shows the likely cost, sends your request, waits,
and saves the video on your computer.

## What happens after you press the button

1. The tool checks your choices and shows the likely cost.
2. It asks you to confirm, and sends nothing before you say yes. The exception is
   the `--yes` option: with it, you say yes in advance and it does not ask.
3. It sends your request one time and saves the order number.
4. Your request joins a queue, then the video is made. BytePlus does not publish
   a typical time.
5. The tool saves the finished video. If you close it while it waits, the
   order goes on. Wait again and it picks up the same order. Asking for a new
   video makes a new paid order.

## What can go wrong

| What you see | What it means | What to do |
|--------------|---------------|------------|
| The request is not valid | A choice does not fit the model | Change the choice. Nothing was sent |
| Content refused | The words or picture broke a content rule | Change them |
| No access to the model | The model is not switched on | Switch it on in the BytePlus console |
| A limit is reached | Too many requests, or your own limit | Wait, or raise the limit |
| The result is not known | The connection broke after sending | Ask your technical contact to list your tasks before you send again. If your console shows a task list, check there. A second request could cost money twice |
| The link was refused | Probably more than 24 hours passed. This is our assumption | See if a new download works. If not, the video may need to be made again |

## What it costs

You pay for the size and length of the video. Bigger and longer costs more.

Example: a 5-second video, wide screen, with the model
`seedance-1-0-pro-250528`:

| Picture quality | One video | Ten videos |
|-----------------|-----------|------------|
| 480p (small) | $0.12 | $1.22 |
| 720p (medium) | $0.26 | $2.57 |
| 1080p (large) | $0.61 | $6.12 |

These are estimates from the list prices read on 2026-11-23. Prices can change.
Your bill uses the amount BytePlus measures. In our one real run it was 2.1%
above the estimate. This tool cannot
show the billed amount. In the BytePlus console, Billing overview shows your
account balance and Usage statistics shows token usage.

## How to control spending

- **Choose the model, picture quality and length.** These set the price. Try an
  idea small and short first.
- **Estimate first.** It is free.
- **Confirm.** Read the cost before you say yes.
- **Set a usage limit** for each model. BytePlus counts your total use and refuses
  requests when the limit is reached (source S15 in `docs/API_NOTES.md`).
- **Use the offline option** if you can wait hours. It is half price, on the 1.0
  models only.
- **Failed videos are not charged.** The BytePlus price page says you pay only
  for videos that succeed.
- **Download within 24 hours.** The link stops working after that.
