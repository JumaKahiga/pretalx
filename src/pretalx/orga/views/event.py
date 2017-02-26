from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.urlresolvers import reverse
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DetailView, UpdateView

from pretalx.event.models import Event
from pretalx.orga.authorization import OrgaPermissionRequired
from pretalx.orga.forms import EventForm
from pretalx.person.models import User


@method_decorator(user_passes_test(lambda u: u.is_superuser), name='dispatch')
class EventCreate(CreateView):
    model = Event
    form_class = EventForm
    template_name = 'orga/event/create.html'
    context_object_name = 'event'

    def get_success_url(self) -> str:
        return reverse('orga:event.view', kwargs={'event': self.object.slug})

    def form_valid(self, form):
        messages.success(self.request, 'Yay!')
        ret = super().form_valid(form)
        return ret


class EventDetail(OrgaPermissionRequired, DetailView):
    model = Event
    slug_url_kwarg = 'event'
    slug_field = 'slug'
    template_name = 'orga/event/detail.html'


class EventUpdate(OrgaPermissionRequired, UpdateView):
    model = Event
    slug_url_kwarg = 'event'
    slug_field = 'slug'
    form_class = EventForm
    template_name = 'orga/event/create.html'

    def get_queryset(self):
        return Event.objects.filter(permissions__user=self.request.user)

    def get_initial(self):
        initial = super().get_initial()
        initial['permissions'] = User.objects.filter(
            permissions__is_orga=True,
            permissions__event=self.object
        )
        return initial

    def get_success_url(self) -> str:
        return reverse('orga:event.view', kwargs={'event': self.object.slug})

    def form_valid(self, form):
        messages.success(self.request, 'Yay!')
        ret = super().form_valid(form)
        return ret
