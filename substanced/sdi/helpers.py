import base64
import math
import operator
import transaction
import urlparse

from pyramid_zodbconn import get_connection

from zope.interface.interfaces import IInterface

from pyramid.renderers import get_renderer
from pyramid.request import Request
from pyramid.httpexceptions import HTTPBadRequest
from pyramid.location import lineage
from pyramid.traversal import find_interface
from pyramid.security import has_permission

from ..util import oid_of
from ..interfaces import ISite

MANAGE_ROUTE_NAME = 'substanced_manage'

def get_mgmt_views(request, context=None):
    registry = request.registry
    if context is None:
        context = request.context
    introspector = registry.introspector
    L = []

    # create a dummy request signaling our intent
    req = Request(request.environ.copy())
    req.script_name = request.script_name
    req.context = context
    req.matched_route = request.matched_route
    req.method = 'GET' 
    req.registry = request.registry

    for data in introspector.get_category('sdi views'): 
        related = data['related']
        sdi_intr = data['introspectable']
        tab_title = sdi_intr['tab_title']
        tab_condition = sdi_intr['tab_condition']
        if tab_condition is not None:
            if tab_condition is False or not tab_condition(request):
                continue
        for intr in related:
            view_name = intr['name']
            if view_name == '' and tab_title == 'manage_main':
                continue # manage_main view
            if intr.category_name == 'views' and not view_name in L:
                derived = intr['derived_callable']
                # do a passable job at figuring out whether, if we visit the
                # url implied by this view, we'll be permitted to view it and
                # something reasonable will show up
                if IInterface.providedBy(intr['context']):
                    if not intr['context'].providedBy(context):
                        continue
                elif intr['context'] and not isinstance(
                        context, intr['context']):
                    continue
                req.path_info = request.mgmt_path(context, view_name)
                if hasattr(derived, '__predicated__'):
                    if not derived.__predicated__(context, req):
                        continue
                if hasattr(derived, '__permitted__'):
                    if not derived.__permitted__(context, req):
                        continue
                L.append(
                    {'view_name':view_name,
                     'tab_title':tab_title or view_name.capitalize()}
                    )
    selected = []
    extra = []
    
    if hasattr(context, '__tab_order__'):
        tab_order = context.__tab_order__
        for view_data in L:
            for view_name in tab_order:
                if view_name == view_data['view_name']:
                    selected.append(view_data)
                    break
            else:
                extra.append(view_data)
    else:
        extra = L
                
    return selected + sorted(extra, key=operator.itemgetter('tab_title'))

def macros():
    template = get_renderer('templates/master.pt').implementation()
    return {'master':template}

def breadcrumbs(request):
    breadcrumbs = []
    for resource in reversed(list(lineage(request.context))):
        if not has_permission('view', resource, request):
            return []
        url = request.mgmt_path(resource)
        name = resource.__name__ or 'Home'
        icon = request.registry.content.metadata(resource, 'icon')
        active = resource is request.context and 'active' or None
        breadcrumbs.append({'url':url, 'name':name, 'active':active,
                            'icon':icon})
    return breadcrumbs

def get_site_title(request):
    site = find_interface(request.context, ISite)
    return site.title or 'Substance D'

def merge_url(url, **kw):
    segments = urlparse.urlsplit(url)
    extra_qs = [ '%s=%s' % (k, v) for (k, v) in 
                 urlparse.parse_qsl(segments.query, keep_blank_values=1) 
                 if k not in ('batch_size', 'batch_num')]
    qs = ''
    for k, v in sorted(kw.items()):
        qs += '%s=%s&' % (k, v)
    if extra_qs:
        qs += '&'.join(extra_qs)
    else:
        qs = qs[:-1]
    return urlparse.urlunsplit(
        (segments.scheme, segments.netloc, segments.path, qs, segments.fragment)
        )

def get_batchinfo(sequence, request, url=None, default_size=15):
    
    if url is None:
        url = request.url
        
    num = int(request.params.get('batch_num', 0))
    size = int(request.params.get('batch_size', default_size))

    if size:
        start = num * size
        end = start + size
        batch = sequence[start:end]
        last = int(math.ceil(len(sequence) / float(size)) - 1)
    else:
        start = 0
        end = 0
        batch = sequence
        last = 0
        
    first_url = None
    prev_url = None
    next_url = None
    last_url = None
    
    if num:
        first_url = merge_url(url, batch_size=size, batch_num=0)
    if start >= size:
        prev_url = merge_url(url, batch_size=size, batch_num=num-1)
    if len(sequence) > end:
        next_url = merge_url(url, batch_size=size, batch_num=num+1)
    if size and (num < last):
        last_url = merge_url(url, batch_size=size, batch_num=last)
    
    first_off = prev_off = next_off = last_off = ''
    
    if first_url is None:
        first_off = 'off'
    if prev_url is None:
        prev_off = 'off'
    if next_url is None:
        next_off = 'off'
    if last_url is None:
        last_off = 'off'
        
    return dict(batch=batch,
                required=prev_url or next_url,
                size=size,
                num=num,
                first_url=first_url,
                prev_url=prev_url,
                next_url=next_url,
                last_url=last_url,
                first_off=first_off,
                prev_off=prev_off,
                next_off=next_off,
                last_off=last_off,
                start=start,
                end=end,
                last=last)

def check_csrf_token(request):
    if request.POST['csrf_token'] != request.session.get_csrf_token():
        raise HTTPBadRequest('incorrect CSRF token')

def add_undo_info(request, label):
    transaction.setUser(oid_of(request.user))
    transaction.note(label)
    conn = get_connection(request)
    db = conn.db()
    if db.supportsUndo():
        undo = request.session.setdefault('sdi.my_undo', [])
        undo.append(label)
        request.session['sdi.my_undo'] = undo
    
def get_undo_info(request):
    conn = get_connection(request)
    db = conn.db()
    if db.supportsUndo():
        my_txns = request.session.get('sdi.my_undo', [])
        if my_txns:
            last = my_txns[-1]
            return {'id':last[0], 'label':last[1]}
    return None
    
