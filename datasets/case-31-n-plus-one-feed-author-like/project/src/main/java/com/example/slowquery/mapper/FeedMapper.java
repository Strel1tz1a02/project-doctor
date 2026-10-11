package com.example.slowquery.mapper;

import com.example.slowquery.model.Post;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface FeedMapper {

    @Select("SELECT id, author_id, content, created_at_ms FROM posts ORDER BY created_at_ms DESC LIMIT #{size}")
    List<Post> findRecentPosts(@Param("size") int size);

    @Select("SELECT nickname FROM users WHERE id = #{userId}")
    String findNicknameById(@Param("userId") long userId);

    @Select("SELECT COUNT(*) FROM likes WHERE post_id = #{postId}")
    long countLikesByPostId(@Param("postId") long postId);
}
