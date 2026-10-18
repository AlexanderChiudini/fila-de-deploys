<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <meta name="description" content="Uma fila simples e compartilhada para organizar os deploys do seu time.">
    <title>Deploy Queue · Fila de deploys</title>
    @vite(['resources/js/app.js'])
</head>
<body><div id="app"></div></body>
</html>