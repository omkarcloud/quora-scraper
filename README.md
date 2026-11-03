# 💬 Quora Scraper

Quora Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Quora data for free.

## ✨ What Can I Get?

- 💬 **Every answer to any question, in full** — text, links, images, author credential, upvotes, views & AI-answer tags
- ❓ **The view counts Quora hides** — exact question views, followers, merged duplicates, topics & related questions
- 👤 **Full profiles of any writer** — credentials, bio, answers by date or views, posts, followers & who they follow
- 🌐 **Topics with up to 156M followers & any Space** — top writers, answer feeds, posts, admins & contributors

## 🎥 Example: Every Answer to a Quora Question

```json
{
  "per_page": 20,
  "current_page": 1,
  "question": {
    "id": 414400,
    "title": "What is it like to work at SpaceX?",
    "link": "https://www.quora.com/What-is-it-like-to-work-at-SpaceX",
    "answers": 17
  },
  "results": [
    {
      "id": 172846986,
      "link": "https://www.quora.com/What-is-it-like-to-work-at-SpaceX/answer/ix_/Joel-White",
      "text": "Best place on the planet for bleeding edge R&D. At first I thought everyone was half-joking that working a year at SpaceX is like working 7 years anywhere else, but nope; they weren’t joking...",
      "created_at": "2019-10-09T03:00:57Z",
      "stats": { "upvotes": 4208, "views": 321264, "shares": 69, "comments": 101 },
      "author": {
        "id": 4156852,
        "name": "Joel White",
        "link": "https://www.quora.com/profile/Joel-White",
        "credential": "former R&D Video and Telecom Data Specialist at SpaceX (2015-2017)"
      },
      "relation": "direct",
      "is_ai_generated": false
    }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Quora Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/quora-scraper
cd quora-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/questions/answers?question=What-is-it-like-to-work-at-SpaceX"
```

```json
{
  "per_page": 20,
  "current_page": 1,
  "next": "http://localhost:8000/questions/answers?question=What-is-it-like-to-work-at-SpaceX&page=2",
  "question": { "id": 414400, "title": "What is it like to work at SpaceX?", "answers": 17 },
  "results": [
    {
      "id": 15932040,
      "link": "https://www.quora.com/What-is-it-like-to-work-at-SpaceX/answer/Josh-Boehm",
      "text": "SpaceX has become quite a large organization over the last few years, yet it still maintains a startup mentality and feel to it...",
      "created_at": "2015-09-30T15:31:46Z",
      "stats": { "upvotes": 2220, "views": 212402, "shares": 17, "comments": 45 },
      "author": {
        "name": "Josh Boehm",
        "credential": "former Head of Software Quality Assurance at SpaceX (2012-2015)"
      },
      "relation": "direct"
    }
  ]
}
```

All 20 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

20 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Question Answers | `/questions/answers` | Every answer with full text, author, upvotes, views and AI tags |
| Question Details | `/questions/details` | Exact views, followers, answer count, topics and related questions |
| Answer Details | `/answers/details` | One answer's full text, links, images, counts and author |
| Question · Answer · Post Comments | `/questions/comments` · `/answers/comments` · `/posts/comments` | Comment threads with text, author, upvotes, date and replies |
| Question Followers · User Followers | `/questions/followers` · `/users/followers` | Followers with name, credential, follower count and profile link |
| Answer Upvoters | `/answers/upvoters` | Everyone who upvoted an answer, with credential and follower count |
| User Details | `/users/details` | Credentials, bio, follower and content counts, expertise and Spaces |
| User Answers | `/users/answers` | A writer's answers, newest or most viewed first, in full |
| User Posts | `/users/posts` | A writer's posts with full text, counts and Space |
| User Questions | `/users/questions` | Questions a user asked, with answer and follower counts |
| User Following | `/users/following` | The people, topics or Spaces a user follows |
| Topic Details | `/topics/details` | Follower count, topic type and the most viewed writers |
| Topic Answers | `/topics/answers` | The topic's answer feed with full text and each question |
| Space Details | `/spaces/details` | Description, rules, member and post counts, subscription prices |
| Space Posts | `/spaces/posts` | The Space's post feed with full text, upvotes and views |
| Space People | `/spaces/people` | Admins, moderators, contributors and followers with weekly stats |
| Post Details | `/posts/details` | One post's full text, links, images, counts and author |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-quora-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-quora-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-quora-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/users/answers",
    params={"user": "Adam-DAngelo", "sort": "views"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Quora Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Quora%20Scraper%20API.)

[![Ask Us by Email about Quora Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Quora%20Scraper%20API&body=I%20need%20help%20using%20the%20Quora%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/quora-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/quora-scraper)
