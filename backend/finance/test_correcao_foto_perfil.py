"""Tests for profile photo validation and persistence.

Specified in markdowns/correcaoFotoPerfilTest.md.
"""
import base64
import binascii
import struct
import zlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from . import models as m


def make_synthetic_png(width=256, height=256, color=6, extra_chunks=None):
    """Helper to build a synthetic PNG byte string with specified dimensions,

    color type (2=RGB, 6=RGBA), scanlines, and optional metadata chunks.
    """
    def chunk(kind, content):
        return (
            struct.pack('>I', len(content))
            + kind
            + content
            + struct.pack('>I', binascii.crc32(kind + content) & 0xffffffff)
        )

    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0))
    bpp = 4 if color == 6 else 3
    # Filter byte 0 (None) before each row of pixels
    raw_scanlines = (b'\x00' + (b'\x7f\x80\x81\xff' if color == 6 else b'\x7f\x80\x81') * width) * height
    idat = chunk(b'IDAT', zlib.compress(raw_scanlines))

    body = [ihdr]
    if extra_chunks:
        for k, c in extra_chunks:
            body.append(chunk(k, c))
    body.append(idat)
    body.append(chunk(b'IEND', b''))
    return b'\x89PNG\r\n\x1a\n' + b''.join(body)


def to_data_url(raw_bytes, mime='image/png'):
    return f'data:{mime};base64,' + base64.b64encode(raw_bytes).decode()


class PhotoValidationRegressionTests(TestCase):
    """Section 1: Reproduce the real rejection with synthetic fixtures.

    Real browser/WebKitGTK canvas exports routinely include chunks like iCCP, eXIf,
    or bKGD when exporting images. The current backend validator rejects them.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user('photo_tester')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        m.Profile.objects.get_or_create(user=self.user)

    def test_reproduce_real_rejection_png_with_iccp_chunk(self):
        """A valid 256x256 PNG containing an iCCP chunk (ICC profile from canvas export)

        must be accepted by the server. Currently fails with HTTP 400.
        """
        iccp_data = b'sRGB\x00\x00' + zlib.compress(b'synthetic-icc-profile-data-for-test')
        png_with_iccp = make_synthetic_png(256, 256, color=6, extra_chunks=[(b'iCCP', iccp_data)])
        photo_payload = to_data_url(png_with_iccp)

        res = self.client.patch('/api/v1/profile/', {'photo': photo_payload}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        profile = self.client.get('/api/v1/profile/').data
        self.assertTrue(profile['photo'].startswith('data:image/png;base64,'))

    def test_reproduce_real_rejection_png_with_exif_chunk(self):
        """A valid 256x256 PNG with an eXIf chunk must be accepted without error.

        Currently fails with HTTP 400.
        """
        exif_data = b'II*\x00\x08\x00\x00\x00\x00\x00'
        png_with_exif = make_synthetic_png(256, 256, color=6, extra_chunks=[(b'eXIf', exif_data)])
        photo_payload = to_data_url(png_with_exif)

        res = self.client.patch('/api/v1/profile/', {'photo': photo_payload}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_reproduce_real_rejection_png_with_bkgd_chunk(self):
        """A valid 256x256 PNG with a bKGD chunk must be accepted without error.

        Currently fails with HTTP 400.
        """
        bkgd_data = b'\x00\xff\x00\xff\x00\xff'
        png_with_bkgd = make_synthetic_png(256, 256, color=6, extra_chunks=[(b'bKGD', bkgd_data)])
        photo_payload = to_data_url(png_with_bkgd)

        res = self.client.patch('/api/v1/profile/', {'photo': photo_payload}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)


class RealPhotoValidationAndPersistenceTests(TestCase):
    """Section 2: Real validation, boundary conditions, and persistence."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('persist_tester')
        self.other = get_user_model().objects.create_user('other_user')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        m.Profile.objects.get_or_create(user=self.user)
        m.Profile.objects.get_or_create(user=self.other)

    def test_valid_opaque_rgb_256x256_photo(self):
        """Opaque RGB 256x256 photo (color type 2) saves and persists correctly."""
        png_rgb = make_synthetic_png(256, 256, color=2)
        payload = to_data_url(png_rgb)

        res = self.client.patch('/api/v1/profile/', {'photo': payload}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        saved = self.client.get('/api/v1/profile/').data['photo']
        self.assertTrue(saved.startswith('data:image/png;base64,'))

    def test_valid_rgba_256x256_with_transparency(self):
        """RGBA 256x256 photo with transparency (color type 6) saves and persists."""
        png_rgba = make_synthetic_png(256, 256, color=6)
        payload = to_data_url(png_rgba)

        res = self.client.patch('/api/v1/profile/', {'photo': payload}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        saved = self.client.get('/api/v1/profile/').data['photo']
        self.assertTrue(saved.startswith('data:image/png;base64,'))

    def test_replace_existing_photo(self):
        """Uploading a new photo replaces the old photo."""
        photo1 = to_data_url(make_synthetic_png(256, 256, color=2))
        photo2 = to_data_url(make_synthetic_png(256, 256, color=6))

        res1 = self.client.patch('/api/v1/profile/', {'photo': photo1}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        res2 = self.client.patch('/api/v1/profile/', {'photo': photo2}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

        current = self.client.get('/api/v1/profile/').data['photo']
        self.assertNotEqual(current, photo1)

    def test_empty_photo_removes_image(self):
        """Sending photo='' removes the photo."""
        photo = to_data_url(make_synthetic_png(256, 256))
        self.client.patch('/api/v1/profile/', {'photo': photo}, format='json')

        res_clear = self.client.patch('/api/v1/profile/', {'photo': ''}, format='json')
        self.assertEqual(res_clear.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/v1/profile/').data['photo'], '')

    def test_patch_without_photo_preserves_existing_photo(self):
        """PATCH without photo key preserves the existing photo."""
        photo = to_data_url(make_synthetic_png(256, 256))
        self.client.patch('/api/v1/profile/', {'photo': photo}, format='json')

        res_update = self.client.patch('/api/v1/profile/', {'display_name': 'Nome Atualizado'}, format='json')
        self.assertEqual(res_update.status_code, status.HTTP_200_OK)

        profile = self.client.get('/api/v1/profile/').data
        self.assertEqual(profile['display_name'], 'Nome Atualizado')
        self.assertTrue(profile['photo'].startswith('data:image/png;base64,'))

    def test_legacy_1x1_rgba_png_still_accepted(self):
        """Legacy 1x1 RGBA PNG remains accepted."""
        png_1x1 = make_synthetic_png(1, 1, color=6)
        res = self.client.patch('/api/v1/profile/', {'photo': to_data_url(png_1x1)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_reject_invalid_base64_without_500(self):
        """Corrupt base64 string must return 400, never 500."""
        res = self.client.patch('/api/v1/profile/', {'photo': 'data:image/png;base64,not-valid-base64!@#$'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_truncated_png_without_500(self):
        """Truncated PNG bytes must return 400, never 500."""
        png = make_synthetic_png(256, 256)[:30]
        res = self.client.patch('/api/v1/profile/', {'photo': to_data_url(png)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_invalid_crc_without_500(self):
        """PNG with corrupt CRC in chunk must return 400, never 500."""
        png = bytearray(make_synthetic_png(256, 256))
        # Corrupt bytes in the IHDR chunk CRC
        png[25] ^= 0xff
        res = self.client.patch('/api/v1/profile/', {'photo': to_data_url(bytes(png))}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_fake_signature_without_500(self):
        """File with fake or missing PNG header must return 400, never 500."""
        fake_png = b'NOT_A_PNG_FILE_HEADER' + b'\x00' * 50
        res = self.client.patch('/api/v1/profile/', {'photo': to_data_url(fake_png)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_svg_and_non_png_mime(self):
        """SVG or JPEG mime types disguised as photo must return 400."""
        res_svg = self.client.patch('/api/v1/profile/', {'photo': 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='}, format='json')
        self.assertEqual(res_svg.status_code, status.HTTP_400_BAD_REQUEST)

        res_jpg = self.client.patch('/api/v1/profile/', {'photo': 'data:image/jpeg;base64,dGVzdA=='}, format='json')
        self.assertEqual(res_jpg.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_dimensions_exceeding_512(self):
        """Images larger than 512x512 must return 400."""
        png_large = make_synthetic_png(600, 600)
        res = self.client.patch('/api/v1/profile/', {'photo': to_data_url(png_large)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_payload_exceeding_max_length(self):
        """Payload exceeding serializer max_length (400.000 chars) returns 400."""
        excessive = 'data:image/png;base64,' + 'A' * 400001
        res = self.client.patch('/api/v1/profile/', {'photo': excessive}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_failure_preserves_previously_saved_data(self):
        """Failed photo update does not erase the previously saved photo or name."""
        good_photo = to_data_url(make_synthetic_png(256, 256))
        self.client.patch('/api/v1/profile/', {'display_name': 'Original', 'photo': good_photo}, format='json')

        # Try to send corrupt photo
        self.client.patch('/api/v1/profile/', {'photo': 'data:image/png;base64,corrupt'}, format='json')

        profile = self.client.get('/api/v1/profile/').data
        self.assertEqual(profile['display_name'], 'Original')
        self.assertTrue(profile['photo'].startswith('data:image/png;base64,'))

    def test_user_isolation(self):
        """Another user's profile photo is isolated and cannot be modified."""
        photo = to_data_url(make_synthetic_png(256, 256))
        self.client.patch('/api/v1/profile/', {'photo': photo}, format='json')

        # Switch to other user
        self.client.force_authenticate(self.other)
        other_profile = self.client.get('/api/v1/profile/').data
        self.assertEqual(other_profile['photo'], '')
