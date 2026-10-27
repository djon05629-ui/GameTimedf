from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import ClubSettings, Equipment, User, Zone


class StyledMixin:
    """Добавляет CSS-классы виджетам, чтобы формы выглядели единообразно."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = "check"
            else:
                w.attrs["class"] = "input"


class RegisterForm(StyledMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "email")
        labels = {"username": "Логин", "first_name": "Имя"}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Этот email уже зарегистрирован. Войдите или используйте другой адрес.")
        return email


class ProfileForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Имя", "last_name": "Фамилия"}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Этот email уже занят другим пользователем.")
        return email


class EquipmentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ("name", "zone", "kind", "specs", "hourly_rate", "is_active")
        widgets = {"specs": forms.Textarea(attrs={"rows": 4})}


class ZoneForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Zone
        fields = ("name",)


class ClubSettingsForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = ClubSettings
        fields = ("opening_time", "closing_time", "timezone")
        widgets = {
            "opening_time": forms.TimeInput(attrs={"type": "time", "step": 1800}, format="%H:%M"),
            "closing_time": forms.TimeInput(attrs={"type": "time", "step": 1800}, format="%H:%M"),
        }


class DateRangeForm(StyledMixin, forms.Form):
    date_from = forms.DateField(label="С", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="По", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_from"] > data["date_to"]:
            raise forms.ValidationError("Дата «С» не может быть позже даты «По».")
        return data
