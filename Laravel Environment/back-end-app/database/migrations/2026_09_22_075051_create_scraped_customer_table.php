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
        Schema::create('scraped_customer', function (Blueprint $table) {
            $table->id();
            $table->string('customer_id');
            $table->string('room_type_id');
            $table->string('ota_source');
            $table->integer('price')->nullable();
            $table->string('perks')->nullable();
            $table->dateTime('scraped_at');
            $table->dateTime('target_date');
            $table->integer('category')->nullable();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('scraped_customer');
    }
};
