# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: Python app with a local HTML/CSS/JS interface inside a native Windows window (pywebview, WebView2), compiled with PyInstaller and shipped through an installer. Chosen because the sending engine is Python and an HTML surface allows a careful visual finish.

## Users

Primary: collections or customer-service staff, non-technical, running an overdue-payment notice campaign on a Windows desktop in an office, usually with phones and a spreadsheet open beside them. Support: the IT analyst who sets up credentials and helps when something stops.

## Product Purpose

Turn a spreadsheet of overdue accounts into individual notices by e-mail, WhatsApp and SMS, asking customers to contact the company. Success means every person is reached exactly once per channel, nobody is charged by mistake, and the WhatsApp number is not lost.

## Positioning

A careful sender, not a blaster: it paces itself, stops by itself when something looks wrong, offers a rehearsal with internal contacts, and shows person by person who was told what.

## Operating Context

Flow: load the spreadsheet, review who is held back and why, write the messages, rehearse with internal contacts, pilot with a few people, then run the campaign. WhatsApp needs a QR code read once. Sending lasts hours or days, inside a time window, so the app stays open and must be readable at a glance from across the desk. Customer service adds people to a do-not-send list while it runs.

## Capabilities and Constraints

- Channels: e-mail by Microsoft Graph (a sender mailbox such as noreply@ in your tenant), WhatsApp Web through local Chrome or Edge, SMS queued but waiting for a gateway.
- One message per contact, listing every name, registration number and open installments tied to that contact.
- Money values are never shown in messages.
- Real sending requires an explicit confirmation.
- Unconfirmed sends are held for a person to check, never resent automatically.
- WhatsApp Web automation may break WhatsApp's Terms of Service; pacing reduces block risk but does not remove it. Limits are not public, so speeds are estimates. Prefer the official WhatsApp Business API in production.
- Terms: cliente, inscrição, parcelas, título vencido, ensaio, disparo.

## Brand Commitments

No company branding in the code: the e-mail header uses the `empresa` setting from `config.toml`, and the window shows a neutral "Campanha de Avisos" mark (`disparo/ui/logo.svg`). Voice: welcoming, clear, factual; short sentences, no urgency language, no emoji. Brief: minimalist, clean, delicate, simple and explicit to use.

## Evidence on Hand

Customer data must not appear in screenshots, design assets, tests or the repository; demonstration data must be fictional (`tests/demo_janela.py` builds a synthetic spreadsheet).

## Product Principles

- The next step is always obvious, and only one thing is asked at a time.
- Nothing irreversible happens without the person seeing exactly what will go out.
- Stopping is a safe, normal state, explained in plain language with what to do next.
- Every number on screen comes from the real queue, never from an estimate dressed as fact.
- Calm under pressure: the work is about money owed by people who may be going through a hard time.

## Accessibility & Inclusion

WCAG AA contrast, full keyboard use, status never conveyed by color alone, reduced motion respected, legible from a distance for long-running monitoring.
