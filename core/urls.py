from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("demo/", views.load_demo, name="load_demo"),
    path("chat/", views.chat, name="chat"),
    path("chat/voice/", views.chat_voice, name="chat_voice"),   # parler au chatbot (tounsi)
    path("chat/tts/", views.chat_tts, name="chat_tts"),         # relire un message avec la voix tunisienne
]
