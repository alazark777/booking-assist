# Appointment Booking Agent: Problem Statement and Workflow

Status: Draft for business review. All business details and targets below are assumptions, not approved requirements.

## 1. Problem statement

Customers currently call customer support to book service appointments. Staff manually collect their preferences, check the scheduling system, and create bookings. This requires staff time and limits self-service outside support hours.

Provide a website chat assistant that helps existing customers find an available appointment and book it after their explicit confirmation. The intended outcome is fewer routine bookings requiring staff assistance, while keeping appointment details accurate and providing a clear handoff for exceptions.

## 2. Assumptions and scope

- Customers are signed in to an existing account; the website supplies their verified identity.
- The initial release supports English and new appointments for a defined catalog of services and locations.
- The scheduling system is the source of truth for services, duration, availability, and confirmed bookings.
- The scheduling system provides interfaces to retrieve availability, create bookings, and check a booking's status. These capabilities require validation with its owner.
- Each booking is for one customer, one service, one location, and one available slot. Times are displayed with the location's time zone.
- No payment is required. Cancellations, rescheduling, group bookings, and exceptions to business rules are outside the initial scope.
- Staff handle exceptions during support hours; outside those hours, customers can request follow-up through the existing support process.
- The agent may check availability without confirmation, but must obtain explicit customer confirmation before creating a booking.

## 3. Proposed success measures

During a four-week pilot, aim for at least 60% of eligible booking conversations to result in a confirmed appointment without staff assistance. An eligible conversation is a signed-in customer's request for a supported new appointment; failed and abandoned attempts remain in the denominator.

Track staff handoff rate and booking errors alongside completion. Every reported success must have a confirmed booking reference from the scheduling system, and every booking must have prior customer confirmation. The business owner must validate the target against current booking volumes and performance.

## 4. Main booking workflow

| Step | Customer and agent interaction | Required result |
| --- | --- | --- |
| 1. Establish identity | Use the signed-in customer account. If the session has expired, ask the customer to sign in again. | Verified customer identity. |
| 2. Collect preferences | Ask for the service, location, and preferred date or time range. Clarify missing or ambiguous details. | A complete, supported appointment request. |
| 3. Check availability | Query the scheduling system using those preferences and applicable booking rules. | Current available slots. |
| 4. Select a slot | Present a small set of available options, including date, time, and time zone. Ask the customer to choose. | One selected slot. |
| 5. Obtain confirmation | Summarize the service, location, date, time, and customer details needed for the booking. Ask explicitly whether to book it. | Explicit customer approval of the exact appointment. |
| 6. Create the booking | Submit the approved details. The scheduling system validates availability and prevents conflicting reservations. | A confirmed booking reference or a clear failure result. |
| 7. Return confirmation | Show the booking reference and appointment details. The existing scheduling system sends its standard confirmation notification. | The customer knows the appointment is booked. |

## 5. Exception paths

| Situation | Required behavior |
| --- | --- |
| No matching slots | Offer alternative dates or locations. If none are acceptable, offer staff assistance. |
| Slot becomes unavailable before booking | Explain that availability changed, retrieve new options, and obtain confirmation for any replacement slot. |
| Customer changes details or declines confirmation | Update the request and repeat the relevant steps; do not create a booking until the revised details are confirmed. |
| Booking request times out and its outcome is unknown | Check whether the booking was created before retrying. Use duplicate prevention supported by the scheduling system; escalate if the outcome cannot be established. |
| Scheduling system is unavailable | Explain that booking cannot be completed now and offer staff assistance or follow-up. Do not claim success. |
| Unsupported request, unresolved ambiguity, or customer requests a person | Hand off with the collected preferences and any known booking status, so the customer does not have to repeat the request. |
| Notification fails after a successful booking | Preserve the confirmed booking, show its reference in chat, and route the notification issue for follow-up. Do not create another booking. |

## 6. System dependencies and review

| Dependency | Capability to confirm with its owner |
| --- | --- |
| Website and customer account system | Chat entry point and trusted customer identity. |
| Scheduling system | Service catalog, booking rules, availability, booking creation, status lookup, and duplicate prevention. |
| Existing notification service | Delivery of appointment confirmations and handling of delivery failures. |
| Customer support system | Staff handoff or follow-up request containing the conversation summary and booking status. |

Review this draft with the business owner, customer support lead, and scheduling-system owner. Confirm scope, booking rules, success measures, and interface capabilities before proceeding to solution design.
