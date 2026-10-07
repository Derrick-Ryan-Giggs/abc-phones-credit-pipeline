# Charts explained in plain language

For anyone who does not work with data. Figures are from the December 2025 run. "Loan" and "customer" mean the same thing here: each loan is one customer's phone on installments.

## Words used in the charts

| Term | Meaning |
|---|---|
| Behind on payments | 8 to 90 days late on a payment |
| Seriously behind | 31 to 90 days late |
| Lost loan | 91 or more days late. ABC Phones treats these as written off |
| Snapshot | A copy of the whole loan book on one date. We have five: 1 Jan, 31 Mar, 30 Jun, 30 Sep, 30 Dec 2025 |
| Financed loan | A phone bought on installments (cash sales are left out) |

---

## Chart 1: How the loan book performed across 2025 (`portfolio_trends.png`)

Six small charts, each with its own colour. The book more than doubled during the year, from 8,496 loans to 19,565, so every line has to be read against that growth.

### Orange line: customers behind on payments (8 to 90 days late)

- **What it shows:** 17.3%, 19.4%, 17.6%, 18.0%, 17.6%. Roughly 1 customer in 6 is behind at any time, and the figure hardly moves.
- **Why it stays flat:** it is a conveyor belt. Each quarter about 11 to 13 in every 100 customers who were up to date slip into 8 to 90 days late. Most customers who were already late then keep slipping: between snapshots, 65% to 85% of them went past 91 days and left this group (they now show up in the purple line). Only 3% to 6% caught up. New customers come in and the lost ones leave, so the share barely changes.
- **The March bump (19.4%):** in March the older loans were 20.5% behind, against 17.3% in January, and 85% of customers who were late in January had gone past 91 days by March, the biggest sweep of the year. The data cannot say why March was harder. Seasonal cash pressure or collections capacity are possible, and the collections team should be asked.
- **A healthy sign hidden in the flat line:** newer customers start better. Customers who joined in a given quarter were 17%, 15%, 13% and 12% behind at their first snapshot, against 20% to 21% for older loans. The older loans are getting worse as they age (17% to 21%), and the better newcomers offset that.

### Red line: customers seriously behind (31 to 90 days late)

- **What it shows:** 11.1%, 12.7%, 11.5%, 11.8%, 11.3%.
- **Why:** it is the more serious part of the orange group, so it has the same shape and the same March bump, for the same reasons. About 1 customer in 9 is in this state at any time.

### Purple line: lost loans, 91 or more days late

- **What it shows:** 23.4%, 26.3%, 26.6%, 27.3%, 26.3%. About 1 in 4 of all loans ever sold is now 91+ days late.
- **Why it is high and then flat:** lost loans never leave the data, so the share can only grow through new losses and shrink through new sales. About 770 to 890 loans crossed the 91-day line each quarter. As a share of the book at the start of each quarter that is falling: 9.1%, 7.8%, 6.8%, 5.5%. The headline rate flattens because the book is growing fast and about 1 loan in 5 in December was sold in the last three months, so it has not had time to go bad.
- **Careful:** a flat line here does not mean credit quality stopped mattering. It will keep creeping up as the newest loans age.

### Green line: money collected

- **What it shows:** 94.6%, 93.5%, 93.1%, 93.6%, 94.2%. Of every 100 KES that should have been paid by now, about 94 KES was.
- **Why it is so high:** it only counts customers still being collected from. Lost loans are not in it. It also means the line cannot show how bad the lost loans are.
- **Why the dip in June:** customers who joined in the April to June quarter collected only 91.1%, against 93.6% for older loans. Later groups paid on par (93.6% and 94.0%), so the line recovered. The data cannot say why that spring group paid less.

### Teal line: customers who never made a first payment

- **What it shows:** 7.2%, 6.8%, 6.1%, 5.7%, 5.8%. A steady improvement, then a pause.
- **Why it falls:** the number of such loans grew (608 to 1,130) much more slowly than the book (8,496 to 19,565). The groups that joined during 2025 had 5% to 6% first-payment defaults, against 7.2% in the opening book.
- **Why it stopped falling in December:** the newest group (sold in the last three months) had 7.2% first-payment defaults, the highest of any 2025 group. It is the one number on this chart to watch. It may be timing or a real change in who is being approved, and this data cannot tell which.

### Dark blue line: healthy customers who stayed healthy

- **What it shows:** 93.6%, 94.3%, 95.4%, 95.8%. There is no January point because there is no earlier snapshot to compare with.
- **How it works:** take customers who were up to date or up to 30 days late at the last snapshot. The line is the share who have not since handed back the phone or gone past 91 days late. Paying off the loan counts as staying healthy.
- **Why it improves:** fewer healthy customers are slipping away. The share returning the phone fell from 2.1% to 1.1%, and the share going past 91 days fell from 4.3% to 3.1%.

---

## Chart 2: Customers behind on payments, by monthly income (`segment_risk.png`)

- **How to read it:** each bar is a group of customers by monthly income. The number is how many in every 100 are 8 to 90 days behind. The dashed line is the average (17 in 100). Red bars are more behind than average, green bars fewer, grey about average. The number of loans in each group is in brackets, and small groups are less certain.
- **What it shows:** the lower the income, the more often customers fall behind. 25 in 100 customers earning under 5,000 a month, falling to 13 in 100 for 100,000 to 149,999. Customers earning below 10,000 are 22 in 100 behind, against 14 in 100 for those earning 100,000 or more.
- **How sure we are:** the steady downward pattern is very unlikely to be chance. The single "under 5,000" bar is based on only 170 loans, so on its own it is less reliable than the overall pattern. The small rise at 150,000 or more is within normal variation.
- **Why it might be so:** lower-income customers have less room when money is tight. This shows a pattern, not a proven cause.
- **Only 2025 loans are used:** income and age were only recorded for loans sold from late 2024. Older loans have no income data, and mixing them in would make "no data" look like a customer trait.
- **What to do with it:** test a lighter payment plan or a larger deposit for the lowest-income groups, and track whether lateness falls.

### Customers behind on payments, by age (`segment_risk_age.png`)

- **What it shows:** 20 in 100 for ages 18 to 25, about 17 for 26 to 35, and about 15 to 16 for 36 to 55. The 56 and over group looks high (20 in 100) but has only 73 loans, so it tells us nothing reliable.
- **Takeaway:** age matters much less than income. Young customers are a little higher, but the gap is small.

---

## Chart 3: Customer satisfaction and late payments (`nps_credit.png`)

- **How to read it:** customers answered the survey question "how likely are you to recommend ABC Phones?" from 0 to 10. Each bar is the average answer for customers grouped by how late they were when they answered. Higher is happier.
- **What it shows:** 6.8 for customers up to date, 6.1 for 1 to 30 days late, 5.7 for 31 to 90 days late and 4.3 for over 90 days late. The more behind a customer is, the less they would recommend the company. The big drop is for customers over 90 days late.
- **Why it might be so:** late customers are more likely to be chased, have their phone locked, or be struggling to get help (see chart 4). It could also work the other way, because unhappy customers may be less willing to pay. The data shows a link, not which way it runs.
- **Careful:** the middle groups are small (155 and 88 customers), so the exact gap between 6.1 and 5.7 is not reliable. The pattern and the drop at the end are. Only about 1 loan in 6 has a survey answer.

## Chart 4: Which experiences go with unhappy customers (`nps_experience.png`)

- **How to read it:** for each experience, the green bar is the average rating from customers who did not have the problem, and the red bar is for customers who did.
- **What it shows:** trouble getting help from customer care goes with the biggest gap: 7.7 against 4.4. A locked phone (7.1 against 5.7) and a payment delay (7.1 against 5.8) also lower ratings, but less.
- **Why it matters:** about a third of up-to-date customers report trouble reaching customer care, and the share rises to 4 in 10 or 5 in 10 for customers who are late. Customers who are late and cannot get help rate the company far lower than late customers who can (a net score of about -49 against +18).
- **What it does not show:** late customers who reported difficulty were not more likely to end up lost later, but the sample is small (114 customers), so this cannot be settled.
- **What to do with it:** make customer care easy to reach in the first 1 to 7 days of lateness, with a simple payment plan on offer. It targets the group where trouble is already common, it costs little, and it can be tested by contacting some late customers early and comparing with a group left alone.

---

## Reading all of these safely

- Each chart shows patterns in one year of data from one company. None of them proves a cause.
- Small groups are labelled, and their numbers should not be quoted on their own.
- Where this document says "the data cannot say why", the answer needs the business: the collections team, customer care, and whoever sets the credit approval rules.