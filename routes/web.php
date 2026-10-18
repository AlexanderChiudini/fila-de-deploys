<?php

use App\Http\Controllers\DeploymentController;
use Illuminate\Support\Facades\Route;

Route::view('/', 'queue');
Route::prefix('api/deployments')->group(function () {
    Route::get('/', [DeploymentController::class, 'index']);
    Route::delete('/finished', [DeploymentController::class, 'clearFinished'])->middleware('throttle:60,1');
    Route::post('/', [DeploymentController::class, 'store'])->middleware('throttle:60,1');
    Route::patch('/{deployment}', [DeploymentController::class, 'update'])->middleware('throttle:120,1');
    Route::patch('/{deployment}/move', [DeploymentController::class, 'move'])->middleware('throttle:120,1');
    Route::delete('/{deployment}', [DeploymentController::class, 'destroy'])->middleware('throttle:60,1');
});
