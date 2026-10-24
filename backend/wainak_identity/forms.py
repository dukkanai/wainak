from datetime import date
from django import forms
from wainak.domain import POLICY_VERSION


class EligibilityForm(forms.Form):
    birth_date = forms.DateField()
    is_muslim = forms.BooleanField(required=True)
    terms_version = forms.ChoiceField(choices=[(POLICY_VERSION, POLICY_VERSION)])
    privacy_version = forms.ChoiceField(choices=[(POLICY_VERSION, POLICY_VERSION)])

    def clean_birth_date(self):
        born = self.cleaned_data["birth_date"]
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if not 18 <= age <= 120:
            raise forms.ValidationError("The stated adult eligibility is required.", code="not_eligible")
        return born

    def signup(self, request, user):
        from .repository import service
        domain = service()
        result = domain.register({"email": user.email, "birth_date": self.cleaned_data["birth_date"].isoformat(),
                                  "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        user.domain_id = result["account"]["id"]
        user.save(update_fields=["domain_id"])
        # The domain factory generates a transient development token in Python;
        # it is never exposed and its digest is deleted before the shared commit.
        with domain.repository.transaction() as state:
            for token_hash, actor in list(state.sessions.items()):
                if actor == user.domain_id:
                    del state.sessions[token_hash]
