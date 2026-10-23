# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin, StackedInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Perfil


class PerfilInline(StackedInline):
    """Cargo e filiais aparecem dentro da própria tela do usuário."""
    model = Perfil
    can_delete = False
    verbose_name = "Perfil"
    verbose_name_plural = "Perfil"
    fields = ("cargo", "filiais")
    filter_horizontal = ("filiais",)


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    # Formulários do Unfold (sem eles, os campos de senha ficam sem estilo)
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    inlines = [PerfilInline]
    list_display = ("username", "first_name", "last_name", "filiais_display", "is_active", "is_staff")
    list_select_related = ("perfil",)

    @admin.display(description="Filiais")
    def filiais_display(self, obj):
        perfil = getattr(obj, "perfil", None)
        if perfil is None:
            return "— sem perfil —"
        return ", ".join(f.nome for f in perfil.filiais.all()) or "—"

    def get_inline_instances(self, request, obj=None):
        # Na tela de "Adicionar usuário" (só usuário e senha) o perfil ainda não aparece
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(Perfil)
class PerfilAdmin(ModelAdmin):
    list_display = ("usuario", "filiais_display", "cargo", "criado_em")
    list_filter = ("filiais",)
    search_fields = ("usuario__username", "usuario__email", "cargo")
    filter_horizontal = ("filiais",)

    @admin.display(description="Filiais")
    def filiais_display(self, obj):
        return ", ".join(f.nome for f in obj.filiais.all())

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related("filiais")
        return qs if request.user.is_superuser else qs.none()