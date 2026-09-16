import base64
import binascii
import struct
import zlib
from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from . import models as m
from .api import AUTH, local_request_allowed


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', allow_blank=True, required=False)
    joined_at = serializers.DateTimeField(source='user.date_joined', read_only=True)
    photo = serializers.CharField(allow_blank=True, required=False, max_length=400000)

    class Meta:
        model = m.Profile
        fields = ['display_name', 'email', 'phone', 'bio', 'photo', 'theme', 'joined_at']

    def validate_photo(self, value):
        if not value:
            return ''
        # Browser crops and normalizes uploads to PNG. Validate its complete structure,
        # bounded decoded size and scanlines; discard metadata before persisting.
        try:
            prefix = 'data:image/png;base64,'
            if not value.startswith(prefix):
                raise ValueError()
            raw = base64.b64decode(value[len(prefix):], validate=True)
            if raw[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError()
            pos, chunks, compressed, header = 8, [], b'', None
            ended = False
            while pos < len(raw):
                length = struct.unpack('>I', raw[pos:pos+4])[0]
                kind, body = raw[pos+4:pos+8], raw[pos+8:pos+8+length]
                crc = struct.unpack('>I', raw[pos+8+length:pos+12+length])[0]
                if len(body) != length or binascii.crc32(kind+body) & 0xffffffff != crc:
                    raise ValueError()
                if header is None and kind != b'IHDR':
                    raise ValueError()
                if kind == b'IHDR':
                    if header is not None or length != 13:
                        raise ValueError()
                    width, height, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', body)
                    if not (1 <= width <= 512 and 1 <= height <= 512 and depth == 8 and color in (2, 6) and comp == filt == interlace == 0):
                        raise ValueError()
                    header = body
                elif kind == b'IDAT':
                    compressed += body
                elif kind == b'IEND':
                    if length or pos+12 != len(raw):
                        raise ValueError()
                    ended = True
                elif kind not in (b'sRGB', b'gAMA', b'cHRM', b'pHYs', b'tEXt', b'iTXt'):
                    raise ValueError()
                if kind in (b'IHDR', b'IDAT', b'IEND'):
                    chunks.append(raw[pos:pos+12+length])
                pos += 12+length
            if not ended or not header:
                raise ValueError()
            stride = width * (4 if color == 6 else 3) + 1
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(compressed, stride*height+1)
            if not decoder.eof or decoder.unused_data or len(pixels) != stride*height or any(pixels[i] > 4 for i in range(0, len(pixels), stride)):
                raise ValueError()
            return prefix + base64.b64encode(raw[:8]+b''.join(chunks)).decode()
        except (ValueError, struct.error, binascii.Error, zlib.error):
            raise serializers.ValidationError('Foto inválida. Escolha uma imagem PNG, JPEG ou WebP pelo seletor de foto.')

    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', None)
        if user_data is not None:
            instance.user.email = user_data['email']
            instance.user.save(update_fields=['email'])
        return super().update(instance, validated_data)


@api_view(['GET', 'PATCH', 'DELETE', 'POST'])
@authentication_classes(AUTH)
@permission_classes([AllowAny])
def profile(request):
    if not request.user.is_authenticated:
        if not local_request_allowed(request):
            raise PermissionDenied('Autenticação necessária.')
        if request.method == 'GET':
            return Response({'deleted': True})
        if request.method == 'POST' and request.data.get('confirmation') == 'CRIAR':
            with transaction.atomic():
                state, _ = m.LocalAccountState.objects.select_for_update().get_or_create(pk=1)
                user, _ = get_user_model().objects.get_or_create(username='local')
                state.deleted = False
                state.save(update_fields=['deleted'])
                obj, _ = m.Profile.objects.get_or_create(user=user)
            return Response(ProfileSerializer(obj).data, status=201)
        raise PermissionDenied('A conta foi excluída. Crie um novo espaço para continuar.')
    if request.method == 'POST':
        raise ValidationError('Já existe uma conta ativa.')
    obj, _ = m.Profile.objects.get_or_create(user=request.user)
    if request.method == 'DELETE':
        if request.data.get('confirmation') != 'EXCLUIR':
            raise ValidationError({'confirmation': 'Digite EXCLUIR para apagar o perfil e todos os seus dados financeiros.'})
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            # Follow PROTECT dependencies, deleting only this user's workspace.
            m.Transaction.objects.filter(user=user).delete()
            m.InstallmentPurchase.objects.filter(user=user).delete()
            m.Contribution.objects.filter(user=user).delete()
            m.GoalState.objects.filter(goal__user=user).delete()
            for model in [m.Goal, m.Subscription, m.Invoice, m.Bill]:
                model.objects.filter(user=user).delete()
            m.Balance.objects.filter(account__user=user).delete()
            for model in [m.Card, m.Account, m.Category]:
                model.objects.filter(user=user).delete()
            if settings.LOCAL_MODE and user.username == 'local':
                m.LocalAccountState.objects.update_or_create(pk=1, defaults={'deleted': True})
            user.delete()
        logout(request)
        return Response(status=204)
    if request.method == 'PATCH':
        serializer = ProfileSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(ProfileSerializer(obj).data)
