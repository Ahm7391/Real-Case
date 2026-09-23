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
        Schema::create('prediction_progress', function (Blueprint $table) {
            $table->id();
            $table->string('job_id')->index();
            $table->integer('customer_id')->nullable()->index();
            $table->integer('progress_percent')->default(0);
            $table->string('stage_name')->nullable();
            $table->text('message')->nullable();
            $table->string('status')->default('running');
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('prediction_progress');
    }
};
