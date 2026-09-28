"""Check the internet link against the real Nostr relays.

Run from python-prototype/ with a Python that has the websockets library:

    python3 tools/nostr_live_check.py              # 1. signatures only
    python3 tools/nostr_live_check.py --warning    # 2. also a test warning, round trip
    python3 tools/nostr_live_check.py --sos        # 3. also a test call for help, round trip

1. Sends one short-lived event (kind 20001: relays pass it on but do not keep it) to
   the built-in relays, and prints each relay's answer. A relay that accepts it has
   checked our event ID and BIP-340 signature.
2. Publishes a TEST warning for Katherine, signed with the development key, the way
   the warning app does, and listens for it the way the phone app does, from another
   connection. Then cancels it at once.
3. Publishes a TEST call for help near Katherine from a throwaway identity the way the
   phone app does, listens for it the way another phone app does, then answers it
   with "I'm safe", which replaces it.

2 and 3 go to public relays: an iPhone running a Debug build of Alert Mesh would
show them until they are cancelled or answered. Their words say they are tests.

This is free and unencumbered software released into the public domain.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alertmesh import internet, nostr, places, wire  # noqa: E402
from alertmesh.chat import Identity  # noqa: E402
from alertmesh.node import Node  # noqa: E402
from alertmesh.relays import RelayPool  # noqa: E402
from alertmesh.signer import OfficialAlertSigner, WarningDraft, new_alert_id  # noqa: E402

WAIT_S = 20


def now_ms() -> int:
    return int(time.time() * 1000)


def wait(condition, seconds=WAIT_S) -> bool:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.1)
    return condition()


def answers(pool: RelayPool, event: nostr.Event, relays: list[str], label: str) -> int:
    """Waits for every relay's answer to an event, prints them, returns how many took it."""
    wait(lambda: len(pool.results(event.id)) == len(relays))
    results = pool.results(event.id)
    print(f"\n{label}: event {event.id[:16]}…")
    for url in relays:
        accepted, why = results.get(url, (None, "no answer"))
        mark = "took it" if accepted else ("REFUSED" if accepted is False else "no answer")
        print(f"  {mark:9} {url}" + (f"  ({why})" if why else ""))
    return sum(1 for accepted, _ in results.values() if accepted)


class Air:
    """No Bluetooth here: frames the listening phone would pass on go nowhere."""

    def send(self, frame):
        pass

    def neighbours(self):
        return 0


def listening_phone(choice, town):
    pool = RelayPool()
    node = Node(Identity("Live check", os.urandom(Identity.SEED_LENGTH)), Air(), clock=now_ms)
    link = internet.PhoneLink(pool, choice, node, lambda: [places.geohash_of(town)], now_ms)
    node.on_report = link.report_arrived
    link.set_enabled(True)
    return pool, node, link


def check_signatures() -> bool:
    pool = RelayPool()
    relays = list(nostr.BUILT_IN_RELAYS)
    event = nostr.sign_event(20001, [["t", "alertmesh-live-check"]], "Alert Mesh prototype: signature check")
    pool.publish(event, relays)
    taken = answers(pool, event, relays, "1. Short-lived test event (kind 20001)")
    pool.close()
    return taken > 0


def check_warning(choice, town) -> bool:
    listen_pool, node, _ = listening_phone(choice, town)
    time.sleep(2)  # let the subscriptions reach the relays first
    cell = places.geohash_of(town)[:4]
    draft = WarningDraft(headline="TEST - Alert Mesh prototype check, please ignore",
                         action_text="No action needed. This test is cancelled straight away.",
                         duration_hours=1, area_cells=[cell])
    alert = OfficialAlertSigner().sign(draft, new_alert_id(), now_ms())
    send_pool = RelayPool()
    sender = internet.WarningSender(send_pool, choice)
    sender.enabled = True
    sender.send(wire.encode(alert))
    taken = answers(send_pool, sender.last_event, sender.last_relays, f"2. Test warning for {town.name} (kind 1403)")
    heard = wait(lambda: any(a.alert_id == alert.alert_id for a in node.alerts.live_alerts()))
    print(f"  The listening phone {'got it' if heard else 'did NOT get it'} over the internet.")
    sender.send(wire.encode(OfficialAlertSigner().cancel(alert.alert_id, now_ms())))
    answers(send_pool, sender.last_event, sender.last_relays, "   Its cancellation")
    cancelled = wait(lambda: not node.alerts.live_alerts())
    print(f"  The listening phone {'dropped it' if cancelled else 'still shows it'} after the cancellation.")
    send_pool.close()
    listen_pool.close()
    return taken > 0 and heard and cancelled


def check_sos(choice, town) -> bool:
    listen_pool, listener, _ = listening_phone(choice, town)
    caller_pool, caller, _ = listening_phone(choice, town)
    time.sleep(2)  # let the subscriptions reach the relays first
    here = places.geohash_of(town)
    relays = choice.geo(here[:4])
    report = caller.author.sos(here, "TEST - Alert Mesh prototype check, please ignore", now_ms())
    caller.send_report(report)  # the caller's link puts it online, as the phone app does
    wait(lambda: caller_pool._results)
    [event_id] = list(caller_pool._results)
    event = nostr.Event(event_id, "", 0, 1402, (), "", "")
    taken = answers(caller_pool, event, relays, f"3. Test call for help near {town.name} (kind 1402), to the "
                                                f"{len(relays)} relays nearest {here[:4]}")
    heard = wait(lambda: any(r.report_id == report.report_id for r in listener.reports.live_reports()))
    print(f"  The listening phone {'got it' if heard else 'did NOT get it'} over the internet.")
    caller.send_report(caller.author.safe(None, "", now_ms()))
    answered = wait(lambda: any(r.kind.name == "SAFE" for r in listener.reports.live_reports()))
    print(f"  \"I'm safe\" {'replaced it' if answered else 'did NOT arrive'} on the listening phone.")
    caller_pool.close()
    listen_pool.close()
    return taken > 0 and heard and answered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warning", action="store_true", help="also send and cancel a test warning")
    parser.add_argument("--sos", action="store_true", help="also send and answer a test call for help")
    options = parser.parse_args()
    if os.environ.get(nostr.RELAYS_VARIABLE) is not None:
        print(f"{nostr.RELAYS_VARIABLE} is set; unset it to check the real relays.")
        return 1
    if not RelayPool().available:
        print("Needs the websockets library: python3 -m pip install -r requirements.txt")
        return 1
    choice = internet.RelayChoice.from_environment()
    choice.refresh()
    town = places.find("Katherine")
    ok = check_signatures()
    if options.warning:
        ok = check_warning(choice, town) and ok
    if options.sos:
        ok = check_sos(choice, town) and ok
    print("\nAll good." if ok else "\nSomething did not work: see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
