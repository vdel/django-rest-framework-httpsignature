from django.contrib.auth.models import User
from rest_framework import authentication
from rest_framework import exceptions
from http_signature import HeaderSigner
import re


class SignatureAuthentication(authentication.BaseAuthentication):

    SIGNATURE_RE = re.compile('.+ (.+)$')
    SIGNATURE_HEADERS_RE = re.compile('.+headers="([\sa-z0-9-]+)".*')

    API_KEY_HEADER = 'X-Api-Key'

    def get_signature_from_signature_string(self, signature):
        """Return the signature from the signature header or None."""
        match = self.SIGNATURE_RE.match(signature)
        if not match:
            return None
        return match.group(1)

    def get_headers_from_signature(self, signature):
        """Returns a list of headers fields to sign."""
        match = self.SIGNATURE_HEADERS_RE.match(signature)
        if not match:
            raise exceptions.AuthenticationFailed('Bad signature')
        headers_string = match.group(1)
        return headers_string.split()

    def header_canonical(self, header_name):
        """Translate HTTP headers to Django header names."""
        # Translate as stated in the docs:
        # https://docs.djangoproject.com/en/1.6/ref/request-response/#django.http.HttpRequest.META
        header_name = header_name.lower()
        if header_name == 'content-type':
            return 'CONTENT-TYPE'
        elif header_name == 'content-length':
            return 'CONTENT-LENGTH'
        return 'HTTP_%s' % header_name.replace('-', '_').upper()

    def build_dict_to_sign(self, request, signature_headers):
        """Build a dict with headers and values used in the signature.

        "signature_headers" is a list of lowercase header names.
        """
        d = {}
        for header in signature_headers:
            if header == 'request-line':
                continue
            d[header] = request.META.get(self.header_canonical(header))
        return d

    def build_signature(self, user_api_key, user_secret, request):
        """Return the signature for the request."""
        path = request.get_full_path()
        sent_signature = request.META.get(
            self.header_canonical('Authorization'))
        signature_headers = self.get_headers_from_signature(sent_signature)
        unsigned = self.build_dict_to_sign(request, signature_headers)

        # Sign string and compare.
        signer = HeaderSigner(
            key_id=user_api_key, secret=str(user_secret),
            headers=signature_headers, algorithm='hmac-sha256')
        signed = signer.sign(unsigned)
        return signed['Authorization']

    def fetch_user_data(self, api_key):
        """Retuns a tuple (User instance, API Secret) or None."""
        return None

    def authenticate(self, request):
        # Check for API key header.
        api_key_header = self.header_canonical(self.API_KEY_HEADER)
        api_key = request.META.get(api_key_header)
        if not api_key:
            return None

        # Check if request has a "Signature" request header.
        authorization_header = self.header_canonical('Authorization')
        sent_string = request.META.get(authorization_header)
        if not sent_string:
            raise exceptions.AuthenticationFailed('No signature provided')
        sent_signature = self.get_signature_from_signature_string(sent_string)

        # Fetch credentials for API key from the data store.
        data = self.fetch_user_data(api_key)
        if data is None:
            return None

        user, secret = data

        # Build string to sign from "headers" part of Signature value.
        computed_string = self.build_signature(api_key, secret, request)
        computed_signature = self.get_signature_from_signature_string(
            computed_string)

        if computed_signature != sent_signature:
            raise exceptions.AuthenticationFailed('Bad signature')

        return (user, None)
