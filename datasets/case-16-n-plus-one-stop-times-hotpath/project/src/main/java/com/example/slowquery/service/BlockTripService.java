package com.example.slowquery.service;

import com.example.slowquery.dto.AdjacentTripVO;
import com.example.slowquery.dto.BlockDetailVO;
import com.example.slowquery.dto.BlockTripVO;
import com.example.slowquery.mapper.TripMapper;
import com.example.slowquery.model.StopTime;
import com.example.slowquery.model.Trip;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class BlockTripService {

    private final TripMapper tripMapper;

    public BlockTripService(TripMapper tripMapper) {
        this.tripMapper = tripMapper;
    }

    public BlockDetailVO blockDetails(int size) {
        List<Trip> trips = tripMapper.findRecentTrips(size);
        BlockDetailVO detail = new BlockDetailVO();
        detail.setAdjacentTrips(getNextAndPreviousTripIds(trips));
        detail.setBlockSequences(calculateBlockTripSequence(trips));
        return detail;
    }

    public List<AdjacentTripVO> getNextAndPreviousTripIds(List<Trip> trips) {
        List<AdjacentTripVO> result = new ArrayList<>();
        for (int i = 0; i < trips.size(); i++) {
            Trip trip = trips.get(i);
            List<StopTime> stopTimes = tripMapper.findStopTimesByTripId(trip.getTripId());
            AdjacentTripVO vo = new AdjacentTripVO();
            vo.setTripId(trip.getTripId());
            vo.setBlockId(trip.getBlockId());
            vo.setStopCount(stopTimes.size());
            vo.setPreviousTripId(i > 0 ? trips.get(i - 1).getTripId() : null);
            vo.setNextTripId(i + 1 < trips.size() ? trips.get(i + 1).getTripId() : null);
            result.add(vo);
        }
        return result;
    }

    public List<BlockTripVO> calculateBlockTripSequence(List<Trip> trips) {
        List<BlockTripVO> result = new ArrayList<>();
        int sequence = 1;
        for (Trip trip : trips) {
            List<StopTime> stopTimes = tripMapper.findStopTimesByTripId(trip.getTripId());
            BlockTripVO vo = new BlockTripVO();
            vo.setTripId(trip.getTripId());
            vo.setBlockSequence(sequence++);
            vo.setStopCount(stopTimes.size());
            result.add(vo);
        }
        return result;
    }
}
