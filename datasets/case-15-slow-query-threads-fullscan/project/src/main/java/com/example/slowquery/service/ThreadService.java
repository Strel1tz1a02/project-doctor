package com.example.slowquery.service;

import com.example.slowquery.dto.ThreadTimestamps;
import com.example.slowquery.mapper.ThreadMapper;
import org.springframework.stereotype.Service;

@Service
public class ThreadService {

    private final ThreadMapper threadMapper;

    public ThreadService(ThreadMapper threadMapper) {
        this.threadMapper = threadMapper;
    }

    public ThreadTimestamps maxTimestamps() {
        return threadMapper.selectMaxTimestamps();
    }
}
