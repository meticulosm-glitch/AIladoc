"""Crea/aggiorna il Secret con le password degli utenti locali di AIladoc.

Gira come hook Helm (PreSync con Argo CD) nell'immagine dell'app, parlando direttamente con
l'API di Kubernetes con il token del service account del Job.
- utenti nuovi: password casuale;
- utenti esistenti: password invariata;
- utenti tolti dai values: rimossi dal Secret.
Nei log compaiono solo i nomi utente, mai le password.
"""
import base64
import json
import os
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.request

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
NAME = os.environ["SECRET_NAME"]
USERS = sorted(json.loads(os.environ["LOCAL_USERS"]))
LENGTH = max(16, int(os.environ.get("PASSWORD_LENGTH", "24")))
LABELS = json.loads(os.environ.get("SECRET_LABELS", "{}"))
NS = open(f"{SA}/namespace").read().strip()
TOKEN = open(f"{SA}/token").read().strip()
API = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ['KUBERNETES_SERVICE_PORT']}"
CTX = ssl.create_default_context(cafile=f"{SA}/ca.crt")
ALPHABET = string.ascii_letters + string.digits


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        return json.load(r)


def main():
    path = f"/api/v1/namespaces/{NS}/secrets/{NAME}"
    try:
        current = call("GET", path)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        current = None
    old = (current or {}).get("data") or {}
    data, created = {}, []
    for user in USERS:
        if old.get(user):
            data[user] = old[user]
        else:
            password = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
            data[user] = base64.b64encode(password.encode()).decode()
            created.append(user)
    removed = sorted(set(old) - set(USERS))
    body = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "data": data,
            "metadata": {"name": NAME, "labels": LABELS}}
    if current is None:
        call("POST", f"/api/v1/namespaces/{NS}/secrets", body)
    elif created or removed:
        body["metadata"]["resourceVersion"] = current["metadata"]["resourceVersion"]
        body["metadata"]["annotations"] = current["metadata"].get("annotations") or {}
        call("PUT", path, body)
    print(f"Secret {NS}/{NAME}: nuove password per {created or 'nessuno'}, "
          f"rimossi {removed or 'nessuno'}, invariati {sorted(set(USERS) - set(created))}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print(f"Errore dall'API di Kubernetes: {e.code} {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        sys.exit(1)
