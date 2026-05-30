package com.example.springbootproject5.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.example.springbootproject5.model.Job;

@Repository
public interface JobRepo extends JpaRepository<Job, Long> {
}
