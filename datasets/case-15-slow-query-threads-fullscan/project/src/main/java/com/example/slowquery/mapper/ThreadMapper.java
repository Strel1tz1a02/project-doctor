package com.example.slowquery.mapper;

import com.example.slowquery.dto.ThreadTimestamps;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ThreadMapper {

    @Select(
        "SELECT MAX(updated_at_ms) AS max_updated_at_ms, " +
        "       MAX(recency_at_ms) AS max_recency_at_ms " +
        "FROM threads"
    )
    ThreadTimestamps selectMaxTimestamps();
}
