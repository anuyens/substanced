from pyramid.security import has_permission
from pyramid.httpexceptions import HTTPFound

from ..interfaces import IFolder

from .helpers import (
    get_batchinfo,
    check_csrf_token,
    )

from . import mgmt_view
from .helpers import add_undo_info

# TODO: rename, cut, copy, paste

@mgmt_view(context=IFolder, name='contents', renderer='templates/contents.pt',
           permission='view')
def folder_contents(context, request):
    can_manage = has_permission('manage contents', context, request)
    L = []
    for k, v in context.items():
        viewable = False
        url = request.mgmt_path(v)
        if has_permission('view', v, request):
            viewable = True
        icon = request.registry.content.metadata(v, 'icon')
        data = dict(name=k, deletable=can_manage, viewable=viewable, url=url, 
                    icon=icon)
        L.append(data)
    batchinfo = get_batchinfo(L, request, url=request.url)
    return dict(batchinfo=batchinfo)

@mgmt_view(context=IFolder, name='delete_folder_contents',
           permission='manage contents', tab_condition=False)
def delete_folder_contents(context, request):
    check_csrf_token(request)
    todelete = request.POST.getall('delete')
    deleted = 0
    for name in todelete:
        v = context.get(name)
        if v is not None:
            del context[name]
            deleted += 1
    alert = 'Deleted %s items' % deleted
    request.session.flash(alert)
    add_undo_info(request, alert)
    return HTTPFound(request.mgmt_path(context, '@@contents'))

