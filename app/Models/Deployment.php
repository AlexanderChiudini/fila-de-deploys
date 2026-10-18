<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Deployment extends Model
{
    protected $fillable = ['responsible', 'squad', 'url', 'status', 'notes'];
}
