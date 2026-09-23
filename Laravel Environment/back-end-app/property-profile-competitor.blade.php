{{-- Upcoming changes: changes will be done after changing table scheme --}}
@extends('ecommerce/property-profile-header')

@section('custom-css')
    <link href="{{asset('/assets/plugins/custom/datatables/datatables.bundle.css')}}" rel="stylesheet" type="text/css" />
@endsection

@section('child-js')
<script>
    window.competitorChart = {
        tableUrl:       "{{ route('ecommerce.competitor.aggregate.table') }}",
        noteUrl:        "{{ route('ecommerce.competitor.aggregate.note') }}",
        listUrl:        "{{ route('ecommerce.competitor.aggregate.list') }}",
        lookupUrl:      "{{ route('ecommerce.competitor.aggregate.lookup') }}",
        saveUrl:        "{{ route('ecommerce.competitor.aggregate.save') }}",
        deleteUrl:      "{{ route('ecommerce.competitor.aggregate.delete') }}",
        moreInfoUrl:    "{{ route('ecommerce.competitor.aggregate.moreinfo.get') }}",
        ratesGetUrl:    "{{ route('ecommerce.competitor.aggregate.rates.get') }}",
        rateSaveUrl:    "{{ route('ecommerce.competitor.aggregate.rates.save') }}",
        rateDeleteUrl:  "{{ route('ecommerce.competitor.aggregate.rates.delete') }}",
        addPropertyUrl: "{{ route('ecommerce.competitor.aggregate.addproperty') }}",
        historicalPriceUrlTemplate: "{{ route('ecommerce.competitor.historical_prices', ['competitor_id' => ':id']) }}",
        customerId: {{ (int) $product->customer_id }},
        csrf: "{{ csrf_token() }}"
    };
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="{{asset('/module/js/competitor-price-chart.js?ver='.date('Ymdhis'))}}"></script>
@endsection

@section('property-tab-content')
<div id="propertycompetitor" class="row g-5 g-xxl-8">
    <div class="col-xl-12">
        <div id="ratedata_editor-wrap" class="card mb-5 mb-xxl-8 ">
            <div class="card-header border-0 ">
                <h3 class="card-title align-items-start flex-column">
                    &nbsp;
                </h3>
                <div class="card-toolbar">
                    <a href="{{ route('ecommerce.properties.competitor.insert', ['id' => $pid]) }}" class="btn btn-sm btn-primary">
                        Edit and Add Competitor
                    </a>
                    <input type="hidden" id="customerid" value="{{$product->customer_id}}">
                </div>
            </div>
        </div>
    </div>

    <div class="col-xl-12">
        <div class="card mb-5 mb-xxl-8">
            <div class="card-header border-0 pt-5">
                <h3 class="card-title align-items-start flex-column">
                    <span class="card-label fw-bolder fs-3 mb-1">Competitor Price</span>
                    <span id="competitor_table_subtitle" class="text-muted fw-bold fs-7"></span>
                </h3>
            </div>
            <div class="card-body pt-3" style="position: relative;">
                <div id="competitor_table_wrap">
                    <div class="text-center text-gray-400 py-10">Loading...</div>
                </div>
                <div id="competitor_table_loader" class="overlay-layer card-rounded bg-dark bg-opacity-5 d-none" style="position:absolute;inset:0;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
@endsection
