"""Authenticated same-origin loopback transport for the versioned local API."""
from collections import OrderedDict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
import secrets
import threading
import time
from urllib.parse import parse_qs,urlsplit,unquote
import re
import uuid

from usage_api_contract import ApiError,invalid,strict_json,MAX_URL,MAX_BODY,MAX_RESPONSE
from usage_index_db import IndexBusy,IndexUnavailable,IndexRecoveryError,IndexQueryBudget
from usage_config import SettingsError
from usage_hub import STATIC


class LocalSessions:
    def __init__(self,*,monotonic=time.monotonic):
        self.monotonic=monotonic;self.grants=OrderedDict();self.sessions=OrderedDict();self.lock=threading.Lock()
        self.control=secrets.token_urlsafe(32)

    def issue(self):
        with self.lock:
            token=secrets.token_urlsafe(32);self.grants[token]=self.monotonic()+30
            while len(self.grants)>64:self.grants.popitem(last=False)
            return token

    def exchange(self,token,cookie=''):
        if not isinstance(token,str) or len(token)>128:raise ApiError(403,'launch_required','Open the service through an explicit application launch.')
        with self.lock:
            expires=self.grants.pop(token,None)
            if expires is None or expires<=self.monotonic():raise ApiError(403,'launch_expired','Launch handoff expired or was already used; open again from the application.')
            existing=self._cookie_value(cookie)
            current=self.sessions.get(existing)
            if current and current[1]>self.monotonic():
                self.sessions[existing]=(current[0],self.monotonic()+3600)
                return existing,current[0]
            session,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            self.sessions[session]=(csrf,self.monotonic()+3600)
            while len(self.sessions)>128:self.sessions.popitem(last=False)
            return session,csrf

    @staticmethod
    def _cookie_value(cookie):
        if len(cookie)>4096:return None
        try:
            value=SimpleCookie(cookie).get('usage_hub_v1')
            return None if value is None else value.value
        except Exception:return None

    def authenticate(self,cookie):
        with self.lock:
            session=self.sessions.get(self._cookie_value(cookie))
            return session[0] if session and session[1]>self.monotonic() else None

    def remaining(self,cookie):
        with self.lock:
            session=self.sessions.get(self._cookie_value(cookie))
            return max(0,int(session[1]-self.monotonic())) if session else 0


def static_files():
    # Only shipped application assets; never map an arbitrary URL onto disk.
    files = {'/': ('local.html', 'text/html; charset=utf-8'),
             '/style.css': ('style.css', 'text/css; charset=utf-8')}
    for path in STATIC.glob('*.js'):
        files['/' + path.name] = (path.name, 'text/javascript; charset=utf-8')
    for path in (STATIC / 'assets').glob('*'):
        if path.suffix in ('.svg', '.woff2'):
            files['/assets/' + path.name] = ('assets/' + path.name,
                'image/svg+xml' if path.suffix == '.svg' else 'font/woff2')
    return files


BOOTSTRAP_HTML=b'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Usage Hub local service</title><main><h1>Usage Hub</h1><p id="state">Open this local service through Usage Tray.</p></main><script src="/api-bootstrap.js" defer></script></html>'


def handler_class(service):
    files = static_files()
    class Handler(BaseHTTPRequestHandler):
        server_version='UsageHub'
        sys_version=''
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def log_message(self,*args):pass
        @property
        def origin(self):return f'http://127.0.0.1:{self.server.server_port}'
        def send(self,status,body,*,kind='application/json',cookie=None):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode()
            if len(body)>MAX_RESPONSE:
                status=503;body=json.dumps({'error':{'code':'response_budget','message':'Response exceeds the supported work budget.'},'request_id':uuid.uuid4().hex}).encode()
            self.send_response(status)
            for key,value in {'Content-Type':kind,'Content-Length':str(len(body)),'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
                'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items():self.send_header(key,value)
            if cookie:self.send_header('Set-Cookie',f'usage_hub_v1={cookie}; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=3600')
            try:self.end_headers();self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):self.close_connection=True
        def error(self,error):
            # Drain only a small, already declared body before closing a denied
            # request; unread POST bytes can reset the socket on Windows.
            length=self.headers.get('Content-Length','0')
            if not getattr(self,'body_read',False) and length.isdecimal() and int(length)<=65536 and not self.headers.get('Transfer-Encoding'):
                try:
                    self.connection.settimeout(.1);self.rfile.read(int(length))
                except (OSError,ValueError):pass
                finally:self.connection.settimeout(5)
            body={'error':{'code':error.code,'message':error.message},'request_id':uuid.uuid4().hex}
            if error.field:body['error']['field_errors']={error.field:'Invalid value.'}
            return self.send(error.status,body)
        def boundary(self):
            if self.headers.get_all('Host')!=[self.origin.removeprefix('http://')]:raise ApiError(403,'host_rejected','Request Host is not permitted.')
            origins=self.headers.get_all('Origin') or [None]
            if len(origins)!=1 or origins[0] not in (None,self.origin) or self.headers.get('Sec-Fetch-Site') in ('cross-site','same-site'):
                raise ApiError(403,'origin_rejected','Request origin is not permitted.')
        def body(self):
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length') or [])!=1:raise invalid()
            length=self.headers.get('Content-Length','')
            if not length.isascii() or not length.isdecimal() or not 0<=int(length)<=MAX_BODY:raise invalid()
            types=self.headers.get_all('Content-Type') or []
            if len(types)!=1 or types[0].split(';')[0].strip().lower()!='application/json':raise invalid()
            raw=self.rfile.read(int(length));self.body_read=True
            if len(raw)!=int(length):raise invalid()
            value=strict_json(raw)
            if not isinstance(value,dict):raise invalid()
            return value
        def dispatch(self,method):
            try:
                self.boundary()
                if getattr(self.server,'closing',False):
                    raise ApiError(503,'service_stopping','The local service is stopping; open it again after Quit completes.')
                if len(self.path)>MAX_URL:raise invalid()
                if re.search(r'%(?![0-9a-fA-F]{2})',self.path):raise invalid()
                url=urlsplit(self.path)
                if url.scheme or url.netloc or url.fragment or not self.path.startswith('/') or self.path.startswith('//'):raise invalid()
                decoded=unquote(url.path,encoding='utf-8',errors='strict')
                if any(ord(c)<32 for c in decoded):raise invalid()
                url=url._replace(path=decoded)
                if method=='GET' and url.path=='/service' and not url.query:
                    return self.send(200,BOOTSTRAP_HTML,kind='text/html; charset=utf-8')
                if method=='GET' and url.path in files and not url.query:
                    filename,kind=files[url.path]
                    try:body=(STATIC/filename).read_bytes()
                    except OSError:raise ApiError(503,'asset_unavailable','Local dashboard assets are unavailable; check the installation.') from None
                    if url.path=='/':
                        body=body.replace(b'<html lang="en">',b'<html lang="en" data-api-mode="v1">',1)
                    return self.send(200,body,kind=kind)
                if not url.path.startswith('/api/v1/'):raise ApiError(404,'not_found','Unknown API route.')
                path=url.path.removeprefix('/api/v1')
                if method=='POST' and path=='/local/launch':
                    if url.query or self.headers.get('Origin') is not None or not secrets.compare_digest(self.headers.get('X-Usage-Owner',''),self.server.sessions.control):
                        raise ApiError(403,'owner_required','Application ownership is required.')
                    if self.body():raise invalid()
                    token=self.server.sessions.issue()
                    return self.send(200,service.respond('launch',{'url':self.origin+'/#launch='+token}))
                if method=='POST' and path=='/session/bootstrap':
                    if url.query or self.headers.get('Origin')!=self.origin:raise ApiError(403,'origin_required','A same-origin launch exchange is required.')
                    data=self.body()
                    if set(data)!={'launch_token'}:raise invalid()
                    cookie,csrf=self.server.sessions.exchange(data['launch_token'],self.headers.get('Cookie',''))
                    return self.send(200,service.respond('session',{'csrf_token':csrf,'expires_in_seconds':3600}),cookie=cookie)
                csrf=self.server.sessions.authenticate(self.headers.get('Cookie',''))
                if csrf is None:raise ApiError(403,'session_required','An authenticated local application session is required.')
                if method=='GET':
                    try:params=parse_qs(url.query,keep_blank_values=True,max_num_fields=256,encoding='utf-8',errors='strict')
                    except ValueError:raise invalid() from None
                    if path=='/session':
                        if params:raise invalid()
                        return self.send(200,service.respond('session',{'csrf_token':csrf,'expires_in_seconds':self.server.sessions.remaining(self.headers.get('Cookie',''))}))
                    return self.send(200,service.read(path,params))
                if method not in ('POST','PATCH'):raise ApiError(405,'method_not_allowed','Unsupported API method.')
                if url.query:raise invalid()
                if self.headers.get('Origin')!=self.origin or not secrets.compare_digest(self.headers.get('X-Usage-CSRF',''),csrf):
                    raise ApiError(403,'csrf_required','A same-origin request and session CSRF token are required.')
                status,response=service.mutate(method,path,self.body())
                return self.send(status,response)
            except ApiError as error:return self.error(error)
            except IndexBusy:return self.error(ApiError(503,'index_busy','The local writer is busy; retry after current work completes.'))
            except IndexQueryBudget:return self.error(ApiError(503,'query_budget','Committed query exceeds the supported work budget.'))
            except IndexUnavailable:return self.error(ApiError(503,'index_unavailable','No queryable committed dataset is available; check index status.'))
            except (IndexRecoveryError,SettingsError):return self.error(ApiError(503,'local_recovery_required','Local configuration or index requires recovery; preserve existing files.'))
            except (ValueError,TypeError,OverflowError):return self.error(invalid())
            except Exception:return self.error(ApiError(500,'local_operation_failed','Local operation failed; retry or inspect safe application diagnostics.'))
        def do_GET(self):self.dispatch('GET')
        def do_POST(self):self.dispatch('POST')
        def do_PATCH(self):self.dispatch('PATCH')
        def do_DELETE(self):self.dispatch('DELETE')
        def do_OPTIONS(self):self.error(ApiError(403,'cors_disabled','Cross-origin access is disabled.'))
    return Handler
