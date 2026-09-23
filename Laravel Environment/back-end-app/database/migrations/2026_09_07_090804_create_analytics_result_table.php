<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('analytics_result', function (Blueprint $table) {
            $table->id();
            $table->string('job_id_key');
            $table->integer('customer_id');
            $table->integer('status');
            $table->string('message');
            $table->timestamp('date_request');
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('analytics_result');
    }
};
